import csv
import logging
import re

from tap_spreadsheets_anywhere.configuration import TableSpec

LOGGER = logging.getLogger(__name__)


def generator_wrapper(reader: csv.DictReader, table_spec: TableSpec):
    for row in reader:
        to_return = {}
        if table_spec.skip_empty_rows and all(value == None or value == "" for value in row.values()):
            continue
        for key, value in row.items():
            if key is None:
                key = "_smart_extra"

            formatted_key = key

            # remove non-word, non-whitespace characters
            formatted_key = re.sub(r"[^\w\s]", "", formatted_key)

            # replace whitespace with underscores
            formatted_key = re.sub(r"\s+", "_", formatted_key)

            # preserve mixed casing
            if formatted_key.isupper():
                formatted_key = formatted_key.lower()

            to_return[formatted_key] = value
        yield to_return


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
