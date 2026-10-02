/**
 * Markdown renderer for assistant answers.
 *
 * Supports headings, lists, tables, code blocks, inline math, and renders
 * [1]-style citation markers as interactive chips that open the source.
 */

import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import { cn } from '../../lib/utils'

interface Props {
  content: string
  onCitationClick?: (index: number) => void
  className?: string
}

export function Markdown({ content, onCitationClick, className }: Props) {
  return (
    <div className={cn('markdown', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // Turn [1] markers into buttons that open the cited passage.
          p({ children, ...props }) {
            return <p {...props}>{mapCitations(children, onCitationClick)}</p>
          },
          li({ children, ...props }) {
            return <li {...props}>{mapCitations(children, onCitationClick)}</li>
          },
          td({ children, ...props }) {
            return <td {...props}>{mapCitations(children, onCitationClick)}</td>
          },
          th({ children, ...props }) {
            return <th {...props}>{mapCitations(children, onCitationClick)}</th>
          },
          a({ href, children, ...props }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                {children}
              </a>
            )
          },
          // Code: inline vs block.
          code({ className: cls, children, ...props }) {
            const isBlock = String(cls ?? '').includes('language-')
            if (!isBlock) {
              return (
                <code className={cls} {...props}>
                  {children}
                </code>
              )
            }
            const language = String(cls).replace('language-', '')
            const text = String(children).replace(/\n$/, '')
            return (
              <div className="code-block">
                <div className="code-block-header">
                  <span>{language || 'code'}</span>
                  <CopyCodeButton text={text} />
                </div>
                <pre>
                  <code className={cls} {...props}>
                    {children}
                  </code>
                </pre>
              </div>
            )
          },
          table({ children, ...props }) {
            return (
              <div className="table-scroll">
                <table {...props}>{children}</table>
              </div>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

function CopyCodeButton({ text }: { text: string }) {
  return (
    <button
      onClick={() => navigator.clipboard?.writeText(text)}
      className="rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-current/60 transition-colors hover:bg-white/10 hover:text-current"
    >
      Copy
    </button>
  )
}

/** Replace `[n]` text nodes with citation buttons. */
function mapCitations(children: React.ReactNode, onClick?: (i: number) => void) {
  return React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child
    const parts = child.split(/(\[\d+\])/g)
    if (parts.length === 1) return child
    return parts.map((part, i) => {
      const match = /^\[(\d+)\]$/.exec(part)
      if (!match) return part
      const index = Number(match[1])
      if (!onClick) return <span key={i} className="citation-static">{part}</span>
      return (
        <button
          key={i}
          onClick={() => onClick(index)}
          className="citation-chip"
          title={`Open source ${index}`}
        >
          {index}
        </button>
      )
    })
  })
}