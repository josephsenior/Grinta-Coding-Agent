import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";
import { MermaidBlock } from "./MermaidBlock";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

function extractPlainText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractPlainText).join("");
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode };
    return extractPlainText(props.children);
  }
  return "";
}

function isMermaidCodeBlock(children: React.ReactNode): string | null {
  const arr = React.Children.toArray(children);
  const first = arr[0];
  if (!React.isValidElement(first)) return null;
  const p = first.props as { className?: string; children?: React.ReactNode };
  const classStr = typeof p.className === "string" ? p.className : "";
  if (!classStr.includes("language-mermaid")) return null;
  const text = extractPlainText(p.children);
  return text;
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none dark:prose-invert prose-pre:bg-transparent prose-pre:p-0",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: ({ children }) => {
            const mermaidSource = isMermaidCodeBlock(children);
            if (mermaidSource !== null) {
              return <MermaidBlock chart={mermaidSource} />;
            }
            return (
              <pre className="overflow-x-auto rounded-md border border-border/50 bg-muted/40 p-3 text-[12px] leading-relaxed dark:bg-muted/25">
                {children}
              </pre>
            );
          },
          code: ({ children, className: codeClass }) => {
            const isInline = !codeClass;
            return isInline ? (
              <code className="rounded border border-border/40 bg-muted/50 px-1 py-px text-[12px] font-mono">
                {children}
              </code>
            ) : (
              <code
                className={cn(
                  codeClass,
                  "bg-transparent! font-mono text-[12px] text-(--hljs-foreground)",
                )}
              >
                {children}
              </code>
            );
          },
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-primary underline decoration-primary/30 underline-offset-2"
            >
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-md border border-border/40">
              <table className="w-full border-collapse text-[12px]">{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
