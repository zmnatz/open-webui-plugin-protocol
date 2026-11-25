# Third-party notices

`src/owpp/runtime/lib/shared_assets.py` and `src/owpp/runtime/lib/live_reload.py` are the reference implementation of the [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol) by Classic298, vendored unmodified, under this licence:

```
BSD 3-Clause License

Copyright (c) 2026, Classic298

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

`examples/plugins/page_banners/` is a variant of [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) by Classic298, under the same licence and copyright notice as above: `assets/loader.js`, `assets/custom.css` and `function.py` are derived from it, with the changes listed in that plugin's README.

Plugins referenced by `source:` in the examples (such as `inline_visualizer`) are fetched from their own repositories at deploy time, under their own licences, and are not redistributed here.

`examples/plugins/clear_thinking_tags/function.py` is adapted from [Clear thinking tags](https://github.com/Haervwe/open-webui-tools/blob/main/filters/clean_thinking_tags_filter.py) 0.2.1 by Haervwe, from [open-webui-tools](https://github.com/Haervwe/open-webui-tools), with the same behaviour (the changes are listed at the top of the file), under its MIT licence:

```
MIT License

Copyright (c) 2024 Juan Jose Soliz Priore

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

`examples/plugins/vision_router/function.py` is adapted from [Dynamic Vision Router](https://github.com/open-webui/functions/tree/main/functions/filters/dynamic_vision_router) 0.1.7 by open-webui and atgehrhardt, adapted to this repository's conventions with the same behaviour (the changes are listed at the top of the file). That repository has no licence file of its own; it is taken to fall under the [Open WebUI License](https://github.com/open-webui/open-webui/blob/main/LICENSE) (BSD 3-Clause plus a branding clause, which forbids removing "Open WebUI" branding and is not touched here), copyright (c) 2023- Open WebUI Inc., all rights reserved, and its redistribution terms apply to this file: the copyright notice above is retained, and the name of the copyright holder and its contributors is not used to endorse this project.

`examples/plugins/theme_designer_pro/` is adapted from [Theme Designer Pro](https://github.com/silentoplayz/theme-designer-pro-presets/tree/34345eaffb8678ddfd38b45d7bc173f5b0d27132) 1.23.0 and its Launcher 2.1.2 by G30, from [silentoplayz/theme-designer-pro-presets](https://github.com/silentoplayz/theme-designer-pro-presets), with the same behaviour apart from one change for Open-WebUI v0.13.5: `function.py`, `tool.py`, `shared.py`, everything in `templates/` and `skills/` are derived from it (the changes are listed at the top of `function.py` and `tool.py`, and in full in that plugin's README), under its MIT licence:

```
MIT License

Copyright (c) 2026 silentoplayz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
