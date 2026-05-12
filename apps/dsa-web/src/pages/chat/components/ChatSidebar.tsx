import type React from 'react';
import type { ChatSessionItem } from '../../../api/agent';

export interface ChatSidebarProps {
  sessions: ChatSessionItem[];
  sessionsLoading: boolean;
  activeSessionId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNewChat: () => void;
}

export const ChatSidebar: React.FC<ChatSidebarProps> = ({
  sessions, sessionsLoading, activeSessionId, onSelect, onDelete, onNewChat,
}) => (
  <>
    <div className="p-3 border-b border-border flex items-center justify-between">
      <span className="text-sm font-medium text-primary">历史对话</span>
      <button
        onClick={onNewChat}
        className="p-1.5 rounded-lg hover:bg-surface-hover transition-colors text-secondary hover:text-primary"
        title="新对话"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
      </button>
    </div>
    <div className="flex-1 overflow-y-auto">
      {sessionsLoading ? (
        <div className="p-4 text-center text-xs text-muted">加载中...</div>
      ) : sessions.length === 0 ? (
        <div className="p-4 text-center text-xs text-muted">暂无历史对话</div>
      ) : (
        sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => onSelect(s.session_id)}
            className={`w-full text-left px-3 py-2.5 border-b border-border hover:bg-surface-hover transition-colors group ${
              s.session_id === activeSessionId ? 'bg-elevated' : ''
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-secondary group-hover:text-primary truncate flex-1">
                {s.title}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.session_id);
                }}
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-surface-hover text-muted hover:text-red-400 transition-all flex-shrink-0"
                title="删除"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
            <div className="text-xs text-muted mt-0.5">
              {s.message_count} 条消息
              {s.last_active &&
                ` · ${new Date(s.last_active).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
            </div>
          </button>
        ))
      )}
    </div>
  </>
);

export default ChatSidebar;
