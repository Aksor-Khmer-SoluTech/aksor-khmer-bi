# Before anything else in the package reads its settings from the environment.
from . import dev_env

dev_env.autoload()
