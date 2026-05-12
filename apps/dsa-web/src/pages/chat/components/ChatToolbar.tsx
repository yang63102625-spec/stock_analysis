import { useState } from 'react';
import type React from 'react';
import { agentApi } from '../../../api/agent';
import { getParsedApiError } from '../../../api/error';
import type { Message } from '../../../stores/agentChatStore';
import { downloadSession, formatSessionAsMarkdown } from '../../../utils/chatExport';

export interface ChatToolbarProps {
  messages: Message[];
  onOpenSidebar: () => void;
}

export const ChatToolbar: React.FC<ChatToolbarProps> = ({ messages, onOpenSidebar }) => {
  const [sending, setSending] = useState(false);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const handlePush = async () => {
    if (sending) return;
    setSending(true);
    setToast(null);
    try {
      const content = formatSessionAsMarkdown(messages);
      await agentApi.sendChat(content);
      setToast({ type: 'success', message: '已发送' });
      setTimeout(() => setToast(null), 3000);
    } catch (err) {
      const parsed = getParsedApiError(err);
      setToast({ type: 'error', message: parsed.message || '发送失败' });
      setTimeout(() => setToast(null), 5000);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-border/50 flex-shrink-0">
      <button
        onClick={onOpenSidebar}
        className="md:hidden p-2 rounded-lg hover:bg-surface-hover transition-colors text-secondary hover:text-primary"
        title="历史对话"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16"/>
        </svg>
      </button>
      <div className="hidden md:block" />
      {messages.length > 0 && (
        <div className="flex gap-2 items-center">
          <button
            type="button"
            onClick={() => downloadSession(messages)}
            className="px-2.5 py-1 rounded-md text-xs text-secondary hover:text-primary
                       bg-surface-hover/50 hover:bg-surface-hover border border-border/60 transition-colors"
            title="导出会话"
          >
            导出
          </button>
          <button
            type="button"
            onClick={handlePush}
            disabled={sending}
            className="px-2.5 py-1 rounded-md text-xs text-secondary hover:text-primary
                       bg-surface-hover/50 hover:bg-surface-hover border border-border/60 transition-colors
                       disabled:opacity-50"
            title="发送到通知渠道"
          >
            {sending ? '发送中...' : '推送'}
          </button>
          {toast && (
            <span className={`text-xs ${toast.type === 'success' ? 'text-emerald-600' : 'text-red-600'}`}>
              {toast.message}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default ChatToolbar;
