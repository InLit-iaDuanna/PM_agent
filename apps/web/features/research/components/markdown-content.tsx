"use client";

import type { ReactNode } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { buildHeadingAnchor } from "./report-version-utils";

type MarkdownVariant = "chat" | "report" | "research";

function extractNodeText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") {
    return "";
  }
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map((item) => extractNodeText(item)).join("");
  }
  if (typeof node === "object" && "props" in node) {
    return extractNodeText(node.props?.children);
  }
  return "";
}

function variantClassName(variant: MarkdownVariant) {
  if (variant === "report" || variant === "research") {
    return "markdown-content markdown-content-report";
  }
  return "markdown-content markdown-content-chat";
}

export function MarkdownContent({
  content,
  variant = "chat",
}: {
  content: string;
  variant?: MarkdownVariant;
}) {
  const renderHeading =
    (Tag: "h1" | "h2" | "h3" | "h4") =>
    ({ children }: { children?: ReactNode }) => {
      const text = extractNodeText(children);
      const anchor = buildHeadingAnchor(text);
      return (
        <Tag id={anchor || undefined}>
          {anchor ? (
            <a className="markdown-heading-anchor" href={`#${anchor}`}>
              {children}
            </a>
          ) : (
            children
          )}
        </Tag>
      );
    };

  return (
    <div className={variantClassName(variant)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: renderHeading("h1"),
          h2: renderHeading("h2"),
          h3: renderHeading("h3"),
          h4: renderHeading("h4"),
          a: ({ node: _node, ...props }) => <a {...props} rel="noreferrer" target="_blank" />,
          table: ({ node: _node, children, ...props }) => (
            <div className="markdown-table-wrap">
              <table {...props}>{children}</table>
            </div>
          ),
          code: ({ className, children, ...props }) => {
            const textContent = String(children).trim();
            const isBlockCode = Boolean(className) || textContent.includes("\n");

            if (!isBlockCode) {
              return (
                <code className={`rounded-md bg-slate-900/6 px-1.5 py-0.5 text-[0.92em] ${className ?? ""}`.trim()} {...props}>
                  {children}
                </code>
              );
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ node: _node, children, ...props }) => (
            <pre {...props}>
              {children as ReactNode}
            </pre>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
