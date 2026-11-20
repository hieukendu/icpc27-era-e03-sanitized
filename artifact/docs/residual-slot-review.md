# Post-hoc review of residual supported targets

The five nominal false twins still receiving slot support after correction were inspected against the frozen source. These observations are assistant-coded, post-hoc, and not independent validation. No input annotation or rule was changed after this inspection.

| Pair | Source | Remaining scope/grounding problem |
|---|---|---|
| 88 | A127 `addlist` | The code converts `v` with `list(v)` and later passes its elements to `self_insert`. The supported flow into that call does not establish the sentence's conversion into “a self_insert.” |
| 94 | A128 `get_str` | The sentence names a list `append`; code uses the method `ret.append`. Name-to-call grounding supplies a path to the return without establishing the asserted list variable. |
| 100 | A125 `__getitem__` | `_get_link_and_move_to_front_of_ll` is called before the cache-miss handler. A call-site match does not support the claim that it is the optional callback invoked on a miss; that callback is `on_miss`. |
| 113 | A129 `from_int` | The list is `parts`, and `append` is its method. Grounding the alleged list name `append` as a call can yield a path into the constructor while missing the role mismatch. |
| 118 | A128 `get_str` | The sentence names a list `extend`; code uses `ret.extend`. A path from the method call to return does not establish a list variable named `extend`. |

These examples separate conversion semantics, conditional scope, and identifier roles from graph/path presence. They show why even a corrected target spelling can retain a scope mismatch. They do not provide gold truth labels for the full planted set.
