"""Single source of model selection for the whole ref/ chain.
FABLE5_MODEL: '0.8b' (default), '2b', '4b' or '9b'.
Unset == today's behavior, byte-identical.

The config JSONs are byte-identical copies of each repo's published
`config.json` (verified against the HuggingFace snapshot at the time they were
added; see evidence/qwen_next/ladder/CHECKPOINT_VERIFY.md).  4b/9b were added
by Track L of the qwen-next de-risking phase for the quality ladder; they are
HOST-side selections only — no RTL exists for either geometry."""
import os

_MODELS = {
    "0.8b": ("qwen3_5_0.8b_config.json", "models--Qwen--Qwen3.5-0.8B"),
    "2b":   ("qwen3_5_2b_config.json",   "models--Qwen--Qwen3.5-2B"),
    "4b":   ("qwen3_5_4b_config.json",   "models--Qwen--Qwen3.5-4B"),
    "9b":   ("qwen3_5_9b_config.json",   "models--Qwen--Qwen3.5-9B"),
}

MODELS = tuple(sorted(_MODELS))     # the valid FABLE5_MODEL values

TAG = os.environ.get("FABLE5_MODEL", "0.8b")
if TAG not in _MODELS:
    raise SystemExit(f"FABLE5_MODEL={TAG!r} not in {sorted(_MODELS)}")
_cfg, REPO_DIR = _MODELS[TAG]
CONFIG_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), _cfg)


def config_json(tag=None):
    """Config path for `tag` (default: the selected model = CONFIG_JSON).

    The selection itself stays frozen at import — every consumer of `TAG` /
    `CONFIG_JSON` behaves exactly as before.  This is for the one kind of
    tool that legitimately reasons about BOTH geometries in a single process
    (`ref/scripts/bytes_per_token.py`, whose self-test validates the 0.8B and
    2B byte budgets against each other), so it does not need a second copy of
    the tag -> file mapping.
    """
    t = TAG if tag is None else str(tag)
    if t not in _MODELS:
        raise SystemExit(f"model {t!r} not in {list(MODELS)}")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        _MODELS[t][0])
