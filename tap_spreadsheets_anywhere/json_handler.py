import json
import re
from json import JSONDecodeError
from jsonpath_ng.ext import parse
import logging

LOGGER = logging.getLogger(__name__)


def generator_wrapper(root_iterator):
    for obj in root_iterator:
        to_return = {}
        if isinstance(obj, list):
            # get json obj from list, yield each one
            my_list = obj
            for obj in my_list:
                yield obj

        for key, value in obj.items():
            if key is None:
                key = "_smart_extra"

            formatted_key = key
            # remove non-word, non-whitespace characters
            formatted_key = re.sub(r"[^\w\s]", "", formatted_key)
            # replace whitespace with underscores
            formatted_key = re.sub(r"\s+", "_", formatted_key)
            to_return[formatted_key.lower()] = value
        yield to_return


def get_row_iterator(table_spec, reader):
    try:
        json_array = json.load(reader)
        json_path = table_spec.get("json_path", None)
        if json_path is not None:
            json_array = extract_jsonpath(json_path, json_array)
            # LOGGER.info(type(json_array))
            # LOGGER.info(json_array)
            for i in json_array:
                LOGGER.info(i)

        # throw a TypeError if the root json object can not be iterated
        return generator_wrapper(iter(json_array))
    except JSONDecodeError as jde:
        if jde.msg.startswith("Extra data"):
            reader.seek(0)
            json_objects = []
            for jobj in reader:
                json_objects.append(json.loads(jobj))
            return generator_wrapper(json_objects)
        else:
            raise jde


def extract_jsonpath(expression, input):
    """Extract records from an input based on a JSONPath expression.

    Args:
        expression: JSONPath expression to match against the input.
        input: JSON object or array to extract records from.
    """
    return [match.value for match in parse(expression).find(input)]
