from dexy.version import VERSION
from ordereddict import OrderedDict
import hashlib
import inspect
import logging
import os
import shutil
import time
import uuid

class Artifact(object):
    META_ATTRS = [
        'binary_input',
        'binary_output',
        'key',
        'ext',
        'stdout',
        'final',
        'additional',
        'initial',
        'state',
        'batch_id'
    ]

    HASH_WHITELIST = [
        'args',
        'artifact_class_source',
        'dexy_version',
        'dirty',
        'dirty_string',
        'ext',
        'filter_name',
        'filter_source',
        'filter_version',
        'next_filter_name',
        'inputs',
        'input_data_dict',
        'input_ext',
        'key'
    ]

    BINARY_EXTENSIONS = [
        '.gif',
        '.jpg',
        '.png',
        '.pdf',
        '.zip',
        '.tgz',
        '.gz',
        '.eot',
        '.ttf',
        '.woff',
        '.swf'
    ]

    def __init__(self):
        if not hasattr(self.__class__, 'SOURCE_CODE'):
            self.__class__.SOURCE_CODE = inspect.getsource(self.__class__)

        self._inputs = {}
        self.additional = None
        self.args = {}
        self.artifact_class_source = self.__class__.SOURCE_CODE
        self.artifacts_dir = 'artifacts' # TODO don't hard code
        self.binary_input = None
        self.binary_output = None
        self.data_dict = OrderedDict()
        self.dexy_version = VERSION
        self.dirty = False
        self.final = None
        self.initial = None
        self.input_data_dict = OrderedDict()
        self.key = None
        self.log = logging.getLogger()
        self.state = 'new'

    def validate(self):
        print "calling validate for", self.key, "in state", self.state
        if self.state == 'new':
            pass
        elif self.state == 'setup':
            pass
        elif self.state == 'pending':
            pass
        elif self.state == 'running':
            pass
        elif self.state == 'complete':
            pass
        else:
            raise Exception("unknown state: %s" % self.state)

    def is_complete(self):
        return self.state == 'complete'

    @classmethod
    def retrieve(klass, hashstring):
        artifact = klass()
        artifact.hashstring = hashstring
        artifact.load()
        return artifact

    def load(self):
        self.load_meta()
        self.load_input()
        if self.is_complete():
            self.load_output()

    def save(self):
        if self.is_abstract():
            pass # For testing.
        elif not self.hashstring:
            raise Exception("can't persist an artifact without a hashstring!")
        else:
            self.save_meta()
            if self.is_complete() and not self.is_output_cached():
                self.save_output()

    def is_abstract(self):
        return not hasattr(self, 'save_meta')

    def setup_from_filter_class(self, filter_class):
        if not hasattr(filter_class, 'SOURCE_CODE'):
            filter_class.SOURCE_CODE = inspect.getsource(filter_class)

        if filter_class.FINAL is not None:
            self.final = filter_class.FINAL

        self.filter_class = filter_class
        self.filter_name = filter_class.__name__
        self.filter_source = filter_class.SOURCE_CODE
        self.filter_version = filter_class.version(self.log)

    def setup_from_previous_artifact(self, previous_artifact):
        assert self.filter_class
        if self.final is None:
            self.final = previous_artifact.final
        self.binary_input = previous_artifact.binary_output
        self.input_ext = previous_artifact.ext
        self.input_data_dict = previous_artifact.data_dict

        # The 'canonical' output of previous artifact
        self.previous_artifact_filename = previous_artifact.filename()
        self.previous_artifact_filepath = previous_artifact.filepath()
        # The JSON output of previous artifact
        if not previous_artifact.binary_output:
            self.previous_cached_output_filepath = previous_artifact.cached_output_filepath()

        self._inputs.update(previous_artifact.inputs())
        # Need to loop over each artifact's inputs in case extra ones have been
        # added anywhere.
        for k, a in previous_artifact.inputs().items():
            self._inputs.update(a.inputs())

        if hasattr(self, 'next_filter_class'):
            next_inputs = self.next_filter_class.INPUT_EXTENSIONS
        else:
            next_inputs = None

        self.ext = self.filter_class.output_file_extension(
                previous_artifact.ext,
                self.name,
                next_inputs
                )
        self.binary_output = self.filter_class.BINARY
        self.state = 'setup'

    @classmethod
    def setup(klass, doc, artifact_key, filter_class = None, previous_artifact = None):
        """Set up a new artifact."""
        artifact = klass()

        artifact.args = doc.args
        artifact.dexy_args = doc.controller.args
        artifact.artifacts_dir = doc.controller.artifacts_dir
        artifact.key = artifact_key
        artifact.log = doc.log
        artifact.name = doc.name

        if artifact.args.has_key('final'):
            artifact.final = artifact.args['final']

        if filter_class:
            artifact.setup_from_filter_class(filter_class)

        if doc.next_filter_class():
            artifact.next_filter_name = doc.next_filter_class().__name__
            artifact.next_filter_class = doc.next_filter_class()

        if previous_artifact:
            artifact.setup_from_previous_artifact(previous_artifact)
        else:
            # This is an initial artifact
            artifact.initial = True
            artifact._inputs = doc.input_artifacts()
            artifact.ext = os.path.splitext(doc.name)[1]
            artifact.binary_input = (doc.ext in artifact.BINARY_EXTENSIONS)
            artifact.set_data(doc.initial_artifact_data())
            if doc.name.startswith("_"):
                artifact.final = False
            artifact.state = 'complete'

        if artifact.binary_output is None:
            artifact.set_binary_from_ext()
        artifact.set_hashstring()
        return artifact

    def run(self):
        self.start_time = time.time()

        if not self.is_complete():
            if not self.filter_class:
                classes = [k for k in self.controller.handlers.values() if k.__name__ == self.filter_name]
                if len(classes) == 0:
                    raise Exception("no filter class %s found" % self.filter_name)
                self.filter_class = classes[0]

            # Set up instance of filter.
            filter_instance = self.filter_class()
            filter_instance.artifact = self
            filter_instance.log = self.log

            self.load_input()
            filter_instance.process()
            # Some check code, maybe remove later.
            if len(self.data_dict) > 0:
                #have data dict in memory
                pass
            elif self.is_canonical_output_cached:
                #have data in file on disk
                pass
            else:
                raise Exception("data neither in memory nor on disk")
            self.state = 'complete'
            self.save()
        else:
            print "cached art", self.key

        self.finish_time = time.time()

    def add_additional_artifact(self, key_with_ext, ext):
        """create an 'additional' artifact with random hashstring"""
        new_artifact = self.__class__()
        new_artifact.key = key_with_ext
        new_artifact.ext = ".%s" % ext
        new_artifact.final = True
        new_artifact.additional = True
        new_artifact.set_random_hashstring()
        new_artifact.set_binary_from_ext()
        new_artifact.artifacts_dir = self.artifacts_dir
        self.add_input(key_with_ext, new_artifact)
        return new_artifact

    def add_input(self, key, artifact):
        self._inputs[key] = artifact

    def inputs(self):
        return self._inputs

    def set_binary_from_ext(self):
        # TODO list more binary extensions or find better way to do this
        if self.ext in self.BINARY_EXTENSIONS:
            self.binary_output = True
        else:
            self.binary_output = False

    def set_data(self, data):
        self.data_dict['1'] = data

    def set_data_from_artifact(self):
        f = open(self.filepath())
        self.data_dict['1'] = f.read()

    def is_loaded(self):
        return hasattr(self, 'data_dict') and len(self.data_dict) > 0

    def hash_dict(self):
        """Return the elements for calculating the hashstring."""
        if self.dirty:
            self.dirty_string = time.gmtime()

        hash_dict = self.__dict__.copy()

        hash_dict['inputs'] = {}
        for k, a in hash_dict.pop('_inputs').items():
            hash_dict['inputs'][k] = a.hashstring

        # Remove any items which should not be included in hash calculations.
        for k in hash_dict.keys():
            if not k in self.HASH_WHITELIST:
                del hash_dict[k]

        return hash_dict

    def set_hashstring(self):
        hash_data = str(self.hash_dict())
        self.hashstring = hashlib.md5(hash_data).hexdigest()

    def set_random_hashstring(self):
        self.hashstring = str(uuid.uuid4())

    def command_line_args(self):
        """
        Allow specifying command line arguments which are passed to the filter
        with the given key. Note that this does not currently allow
        differentiating between 2 calls to the same filter in a single document.
        """
        if self.args.has_key('args'):
            args = self.args['args']
            last_key = self.key.rpartition("|")[-1]
            if args.has_key(last_key):
                return args[last_key]

    def input_text(self):
        text = ""
        for k, v in self.input_data_dict.items():
            text += v
        return text

    def output_text(self):
        text = ""
        for k, v in self.data_dict.items():
            text += v
        return text

    def use_canonical_filename(self):
        """Returns the canonical filename after saving contents under this name
        in the artifacts directory."""
        self.write_to_file(os.path.join(self.artifacts_dir,
                                        self.canonical_filename()))
        return self.canonical_filename()

    def write_to_file(self, filename):
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        shutil.copyfile(self.filepath(), filename)

    def work_filename(self):
        return "%s.work%s" % (self.hashstring, self.input_ext)

    def generate_workfile(self, work_filename = None):
        if not work_filename:
            work_filename = self.work_filename()
        work_path = os.path.join(self.artifacts_dir, work_filename)
        work_file = open(work_path, "w")
        work_file.write(self.input_text())
        work_file.close()

    def temp_filename(self, ext):
        return "%s.work%s" % (self.hashstring, ext)

    def open_tempfile(self, ext):
        tempfile_path = os.path.join(self.artifacts_dir, self.temp_filename(ext))
        open(tempfile_path, "w")

    def temp_dir(self):
        return os.path.join(self.artifacts_dir, self.hashstring)

    def create_temp_dir(self):
        shutil.rmtree(self.temp_dir(), ignore_errors=True)
        os.mkdir(self.temp_dir())

    def canonical_basename(self):
        return os.path.basename(self.canonical_filename())

    def canonical_filename(self):
        fn = os.path.splitext(self.key.split("|")[0])[0]
        return "%s%s" % (fn, self.ext)

    def long_canonical_filename(self):
        return "%s%s" % (self.key.replace("|", "-"), self.ext)

    def filename(self):
        if not hasattr(self, 'ext'):
            raise Exception("artifact %s has no ext" % self.key)
        return "%s%s" % (self.hashstring, self.ext)

    def filepath(self):
        return os.path.join(self.artifacts_dir, self.filename())

