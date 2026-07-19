import React, { useState, useEffect } from 'react';
import { toast } from "react-hot-toast";
import { markdownToHtml } from '../../helpers/markdownHelper';
import { getHost } from '../../helpers/getHost';
import '../../styles/markdown.css';
import Sources from './Sources';

interface ChatResponseProps {
  answer: string;
  metadata?: {
    tool_calls?: Array<{
      tool: string;
      query: string;
      search_metadata: {
        query: string;
        sources: Array<{
          title: string;
          url: string;
          content: string;
        }>
      }
    }>
  }
}

export default function ChatResponse({ answer, metadata }: ChatResponseProps) {
    const [htmlContent, setHtmlContent] = useState('');
    
    // Check if we have sources from a web search tool call
    const hasWebSources = metadata?.tool_calls?.some(
      tool => tool.tool === 'quick_search' && tool.search_metadata?.sources?.length > 0
    );
    
    // Get all sources from web searches
    const webSources = metadata?.tool_calls
      ?.filter(tool => tool.tool === 'quick_search')
      .flatMap(tool => tool.search_metadata?.sources || [])
      .map(source => ({
        name: source.title,
        url: source.url
      })) || [];

    useEffect(() => {
      if (answer) {
        markdownToHtml(answer).then((html) => setHtmlContent(html));
      }
    }, [answer]);
    
    // Format the answer for display
    const formattedAnswer = answer.trim() || '暂无回答。';
    
    const copyToClipboard = () => {
        // Copy the plain text of the answer instead of the HTML
        navigator.clipboard.writeText(formattedAnswer)
            .then(() => {
                toast.success('已复制到剪贴板');
            })
            .catch((err) => {
                console.error('Failed to copy: ', err);
                toast.error('复制失败');
            });
    };

    const forwardToFeishu = async () => {
        const host = getHost();
        try {
            const res = await fetch(`${host}/api/chat/feishu`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: formattedAnswer,
                    title: 'AI 追问回复',
                }),
            });
            const data = await res.json();
            if (res.ok && data.ok) {
                toast.success(data.message || '已推送到飞书');
            } else {
                throw new Error(data.error || '飞书推送失败');
            }
        } catch (err: any) {
            console.error('Feishu forward failed:', err);
            toast.error(err.message || '飞书推送失败');
        }
    };

    const downloadMd = async () => {
        const host = getHost();
        try {
            const res = await fetch(`${host}/api/chat/export`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: formattedAnswer,
                    format: 'md',
                    filename: 'AI回复',
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `下载失败 (${res.status})`);
            }
            const { content, filename } = await res.json();
            const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
            triggerDownload(blob, `${filename || 'AI回复'}.md`);
            toast.success('已下载 Markdown');
        } catch (err: any) {
            console.error('MD download failed:', err);
            toast.error(err.message || '下载失败');
        }
    };

    const triggerDownload = (blob: Blob, filename: string) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        // 延迟清理，确保下载已开始
        setTimeout(() => {
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 100);
    };
  
    return (
      <div className="container flex h-auto w-full shrink-0 gap-4 bg-black/30 backdrop-blur-md shadow-lg rounded-lg border border-solid border-gray-700/40 p-5">
        <div className="w-full">
          <div className="flex items-center gap-3 pb-3">
            <div className="flex items-center justify-center w-6 h-6 rounded-md bg-teal-500/20 border border-teal-500/30">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-teal-400">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </div>
            <h3 className="text-sm font-medium text-teal-200">回答</h3>
          </div>

          <div className="flex flex-wrap content-center items-center gap-[15px] pl-5 pr-5">
            <div className="w-full whitespace-pre-wrap text-base font-light leading-[152.5%] text-white log-message">
              <div
                className="markdown-content prose prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: htmlContent }}
              />
            </div>
          </div>

          {/* Display web search sources if available */}
          {hasWebSources && webSources.length > 0 && (
            <div className="mt-4 pt-3 border-t border-gray-700/30">
              <div className="flex items-center gap-2 mb-2">
                <div className="flex items-center justify-center w-5 h-5 rounded-md bg-blue-500/20 border border-blue-500/30">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-blue-400">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="2" y1="12" x2="22" y2="12"></line>
                    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                  </svg>
                </div>
                <span className="text-xs font-medium text-blue-300">新增来源</span>
              </div>
              <Sources sources={webSources} compact={true} />
            </div>
          )}

          {/* 操作按钮：回答左下角 */}
          <div className="flex items-center gap-3 mt-4 pt-3 border-t border-gray-700/30">
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={copyToClipboard}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-300 hover:text-white bg-gray-800/60 hover:bg-gray-700 border border-gray-700 rounded transition-colors"
              title="复制到剪贴板"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              复制
            </button>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={downloadMd}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-300 hover:text-white bg-gray-800/60 hover:bg-gray-700 border border-gray-700 rounded transition-colors"
              title="下载 Markdown"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              下载
            </button>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={forwardToFeishu}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-300 hover:text-white bg-gray-800/60 hover:bg-gray-700 border border-gray-700 rounded transition-colors"
              title="转发到飞书"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"></path>
                <polyline points="16 6 12 2 8 6"></polyline>
                <line x1="12" y1="2" x2="12" y2="15"></line>
              </svg>
              转发飞书
            </button>
          </div>
        </div>
      </div>
    );
}