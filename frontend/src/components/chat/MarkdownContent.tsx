import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-md bg-zinc-950 p-3 text-sm">
              {children}
            </pre>
          ),
          code: ({ children, className: codeClass }) => {
            const isInline = !codeClass;
            return isInline ? (
              <code className="rounded bg-muted px-1 py-0.5 text-sm font-mono">
                {children}
              </code>
            ) : (
              <code className={cn(codeClass, "text-sm")}>
                {children}
              </code>
            );
          },
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table className="border-collapse border">
                {children}
              </table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
