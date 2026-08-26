// Markdown / JSON 渲染层：marked + highlight.js 的受控封装。
// 语料是本地会话文本，不构成高信任边界：原始 HTML 一律转义成文本，
// 链接只放行 http(s)/mailto 协议（与旧版 util.js marked.use 同策略）。
import { Marked } from 'marked'
import hljs from 'highlight.js'

const esc = (value: unknown) =>
  String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] as string)

const marked = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    // marked v18 renderer：返回字符串替换默认输出
    html(token) {
      return esc((token as { raw?: string }).raw ?? '')
    },
    link(token) {
      const href = token.href || ''
      const text = (token as { text?: string }).text || ''
      if (!/^(https?:)?\/\//i.test(href) && !/^mailto:/i.test(href)) return esc(text)
      return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`
    },
  },
})

/** markdown → HTML；解析失败退化为换行保留的纯文本 */
export function markdownHtml(source: string): string {
  const text = source ?? ''
  try {
    return marked.parse(text, { async: false })
  } catch {
    return esc(text).replace(/\n/g, '<br>')
  }
}

export { esc }

/** 对容器内未高亮的代码块做一次 hljs（.md 内代码 + JSON raw 视图） */
export function highlightIn(root: HTMLElement | null | undefined) {
  if (!root || !hljs) return
  root.querySelectorAll<HTMLElement>('pre code').forEach((el) => {
    if (el.getAttribute('data-highlighted')) return
    try {
      hljs.highlightElement(el)
    } catch {
      /* 高亮失败保留纯文本 */
    }
    el.setAttribute('data-highlighted', '1')
  })
}
