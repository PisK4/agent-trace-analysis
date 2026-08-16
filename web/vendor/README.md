# vendored 前端库

本地优先的零构建前端不再引运行期 CDN，两个渲染库以文件形式收进本目录，随仓库分发。
许可证与源码血缘见各文件头与 `LICENSE.highlight.js`；marked 的 MIT 声明在 `marked.umd.js` 文件头。

| 文件 | 库与版本 | 来源 | 许可证 | 用途 |
| --- | --- | --- | --- | --- |
| `marked.umd.js` | marked 18.0.9 | npm `marked@18.0.9` 的 `lib/marked.umd.js` | MIT | GFM Markdown 解析（表格、列表、代码块） |
| `highlight.min.js` | highlight.js 11.12.0 | `highlightjs/cdn-release@11.12.0/build/highlight.min.js`（common 语言集） | BSD-3-Clause（见 `LICENSE.highlight.js`） | 代码块语法高亮 |
| `marked.umd.js.map` | — | 同上 | MIT | 调试用 source map |

升级方式：重新下载同版本文件覆盖，改动前后跑 `make test` 与手工浏览器验收。
