"""Fast JSON serialization using orjson with stdlib fallback.

orjson is 5-10x faster than stdlib json for both dumps and loads.
It handles numpy types natively (no need for custom encoders).
"""
try:
    import orjson as _json

    def dumps(obj, indent=False, default=None):
        opts = _json.OPT_INDENT_2 if indent else 0
        if default:
            return _json.dumps(obj, option=opts, default=default).decode()
        return _json.dumps(obj, option=opts).decode()

    def loads(s):
        return _json.loads(s)

    def dump(obj, fp, indent=False, default=None):
        fp.write(dumps(obj, indent=indent, default=default))

    def load(fp):
        return loads(fp.read())

except ImportError:
    import json as _json

    def dumps(obj, indent=False, default=None):
        return _json.dumps(obj, indent=2 if indent else None, default=default, separators=(',', ':') if not indent else None)

    def loads(s):
        return _json.loads(s)

    def dump(obj, fp, indent=False, default=None):
        _json.dump(obj, fp, indent=2 if indent else None, default=default)

    def load(fp):
        return _json.load(fp)
