from dexy.filter import DexyFilter
from dexy.utils import parse_yaml
import re

class YamlargsFilter(DexyFilter):
    """
    Strips YAML metadata from top of file and adds this to args for every artifact in current doc.
    """
    ALIASES = ['yamlargs']

    def process_text(self, input_text):
        regex = "\r?\n---\r?\n"
        if re.search(regex, input_text):
            yamlargs, content = re.split(regex, input_text)
            self.update_all_args(parse_yaml(yamlargs))
            return content
        else:
            return input_text
