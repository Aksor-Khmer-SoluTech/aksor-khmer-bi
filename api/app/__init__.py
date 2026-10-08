# Before anything else in the package reads its settings from the environment.
from . import dev_env

dev_env.autoload()

# Where the rendering code looks for fonts added under Resources > Fonts (doc_engine.fonts). Set in every process that
# imports the app -- the API and the job worker both render -- unless the deployment chose a different folder.
import os as _os

from . import font_store as _font_store

_os.environ.setdefault("DOC_ENGINE_FONT_DIRS", str(_font_store.FONT_DIR))
