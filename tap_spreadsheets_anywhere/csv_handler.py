import csv
import io
import logging
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv

from tap_spreadsheets_anywhere.configuration import TableSpec

LOGGER = logging.getLogger(__name__)


def _normalize_key(key):
    if key is None:
        return "_smart_extra"

    formatted_key = key

    # remove non-word, non-whitespace characters
    formatted_key = re.sub(r"[^\w\s]", "", formatted_key)

    # replace whitespace with underscores
    formatted_key = re.sub(r"\s+", "_", formatted_key)

    # preserve mixed casing
    if formatted_key.isupper():
        formatted_key = formatted_key.lower()

    return formatted_key


def generator_wrapper(reader: csv.DictReader, table_spec: TableSpec):
    for row in reader:
        if table_spec.skip_empty_rows and all(value == None or value == "" for value in row.values()):
            continue
        yield {_normalize_key(key): value for key, value in row.items()}


def get_row_iterator(table_spec: TableSpec, reader):
    field_names = table_spec.field_names

    dialect = "excel"
    if table_spec.delimiter is None or table_spec.delimiter == "detect":
        try:
            dialect = csv.Sniffer().sniff(reader.readline(), delimiters=[",", "\t", ";", " ", ":", "|", " "])
            dialect.doublequote = True
            if reader.seekable():
                reader.seek(0)
        except Exception as err:
            raise ValueError("Unable to sniff a delimiter") from err
    else:
        custom_delimiter = table_spec.delimiter
        custom_quotechar = table_spec.quotechar
        if custom_delimiter != "," or custom_quotechar != '"':

            class custom_dialect(csv.excel):
                delimiter = custom_delimiter
                quotechar = custom_quotechar

            dialect = "custom_dialect"
            csv.register_dialect(dialect, custom_dialect)

    reader = csv.DictReader(reader, fieldnames=field_names, dialect=dialect)
    reader.fieldnames = [name.strip() for name in reader.fieldnames]

    return generator_wrapper(reader, table_spec)


def _resolve_delimiter(table_spec: TableSpec, sample_text: str) -> str:
    if table_spec.delimiter is not None and table_spec.delimiter != "detect":
        return table_spec.delimiter
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", "\t", ";", " ", ":", "|", " "])
        return dialect.delimiter
    except Exception as err:
        raise ValueError("Unable to sniff a delimiter") from err


def get_arrow_table(table_spec: TableSpec, binary_reader, data_schema: pa.Schema) -> pa.Table:
    """Read a whole CSV file directly into a pyarrow Table matching `data_schema`.

    The vectorized Arrow BATCH fast path: pyarrow's own C++ CSV parser does both the
    delimiter/quote parsing and the per-column type conversion, replacing
    `generator_wrapper`'s per-row key normalization and `conversion.convert_row`'s
    per-value coercion entirely for this case. Only used for Arrow BATCH mode (see
    `file_utils.write_file`); RECORD mode keeps using `get_row_iterator`, which has to
    emit one message per row regardless of how it parses the file.

    `binary_reader` must be opened in binary mode - pyarrow does its own text decoding
    (`table_spec.encoding`), so a `get_streamreader(..., open_mode="rb")` reader is
    expected, not the text-mode reader `get_row_iterator` uses.
    """
    content = binary_reader.read()
    if not content:
        # Empty file: get_row_iterator's csv.DictReader silently yields zero rows for
        # this case (no error), so match that instead of pyarrow's "Empty CSV file".
        return pa.Table.from_arrays([pa.array([], type=field.type) for field in data_schema], schema=data_schema)

    sample_text = content[:65536].decode(table_spec.encoding, errors="ignore")
    first_line = sample_text.splitlines()[0] if sample_text else ""
    delimiter = _resolve_delimiter(table_spec, first_line)

    if table_spec.field_names:
        raw_names = list(table_spec.field_names)
    else:
        raw_names = [name.strip() for name in next(csv.reader([first_line], delimiter=delimiter))]

    normalized_names = [_normalize_key(name) for name in raw_names]
    column_types = {}
    for raw, normalized in zip(raw_names, normalized_names):
        if normalized not in data_schema.names:
            continue
        target_type = data_schema.field(normalized).type
        if pa.types.is_timestamp(target_type):
            # Read as tz-aware first - pyarrow's timestamp parser requires the source
            # strings to consistently either all carry an explicit UTC offset (this
            # case) or none do; a column that doesn't parse this way raises
            # ArrowInvalid, which the caller (format_handler.get_arrow_table) catches
            # to fall back to the row-by-row path for the file instead of failing it.
            # Cast down to the writer's naive timestamp type once read - the same
            # two-step conversion arrow_batch.rows_to_arrow_table applies for rows
            # coming through that path.
            column_types[raw] = pa.timestamp(target_type.unit, tz="UTC")
        else:
            column_types[raw] = target_type

    parse_options = pa_csv.ParseOptions(
        delimiter=delimiter,
        quote_char=table_spec.quotechar,
        # Python's csv module transparently handles a quoted value spanning multiple
        # physical lines (see the sample_with_bad_newlines.csv fixture and
        # format_handler.monkey_patch_streamreader); pyarrow defaults to False here,
        # which would otherwise silently mis-parse that same case.
        newlines_in_values=True,
    )
    read_options = pa_csv.ReadOptions(
        column_names=raw_names if table_spec.field_names else None,
        encoding=table_spec.encoding,
    )
    convert_options = pa_csv.ConvertOptions(
        column_types=column_types,
        # Replaces pyarrow's default null-token list (which includes "NULL", "NaN", "NA",
        # etc.) with the single check conversion.coerce() makes: only an empty cell is null.
        strings_can_be_null=True,
        null_values=[""],
    )

    table = pa_csv.read_csv(
        io.BytesIO(content),
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
    )
    table = table.rename_columns(normalized_names)

    for field in data_schema:
        if pa.types.is_timestamp(field.type) and field.name in table.column_names:
            index = table.column_names.index(field.name)
            table = table.set_column(index, field, table.column(field.name).cast(field.type))

    if table_spec.skip_empty_rows:
        # A row is empty when every column is null - matches generator_wrapper's row-level
        # check, since null_values=[""] above already makes an originally-empty cell null
        # regardless of column type.
        non_null_mask = None
        for column in table.columns:
            valid = pc.is_valid(column)
            non_null_mask = valid if non_null_mask is None else pc.or_(non_null_mask, valid)
        if non_null_mask is not None:
            table = table.filter(non_null_mask)

    return table
