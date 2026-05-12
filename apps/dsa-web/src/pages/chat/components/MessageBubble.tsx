import type React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../../../stores/agentChatStore';
import { ThinkingBlock } from './ThinkingBlock';

const UserIcon: React.FC = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
  </svg>
);

const BotIcon: React.FC = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
  </svg>
);

const MARKDOWN_PROSE_CLASSES = `prose prose-sm max-w-none text-[13px] leading-relaxed
prose-headings:text-primary prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1.5
prose-h1:text-[15px] prose-h1:border-b prose-h1:border-border/50 prose-h1:pb-1
prose-h2:text-[14px] prose-h3:text-[13px]
prose-p:my-1.5 prose-p:last:mb-0
prose-strong:text-primary prose-strong:font-medium
prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-li:marker:text-secondary
prose-code:text-cyan prose-code:bg-elevated prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-normal
prose-pre:bg-elevated prose-pre:border prose-pre:border-border prose-pre:rounded-lg prose-pre:p-2.5 prose-pre:text-xs
prose-table:w-full prose-table:text-xs prose-table:border-collapse prose-table:border prose-table:border-border prose-table:rounded-lg prose-table:overflow-hidden
prose-thead:bg-elevated/80
prose-th:text-primary prose-th:font-medium prose-th:border prose-th:border-border prose-th:px-2 prose-th:py-1.5 prose-th:text-left
prose-td:border prose-td:border-border prose-td:px-2 prose-td:py-1
prose-tr:even:bg-surface-hover/30
prose-hr:border-border/50 prose-hr:my-2.5
prose-a:text-cyan prose-a:no-underline hover:prose-a:underline
prose-blockquote:border-l-2 prose-blockquote:border-cyan/40 prose-blockquote:bg-elevated/50 prose-blockquote:text-secondary prose-blockquote:pl-3 prose-blockquote:py-1 prose-blockquote:my-2 prose-blockquote:rounded-r`;

export interface MessageBubbleProps {
  message: Message;
  thinkingExpanded: boolean;
  onToggleThinking: () => void;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, thinkingExpanded, onToggleThinking }) => {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''} animate-fade-in`}>
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-semibold shadow-sm ${
        isUser
          ? 'bg-gradient-to-br from-cyan to-blue-600 text-white'
          : 'bg-gradient-to-br from-purple/80 to-indigo-500 text-white'
      }`}>
        {isUser ? <UserIcon /> : <BotIcon />}
      </div>
      <div className={`max-w-[80%] rounded-2xl px-3 py-2 shadow-sm transition-all text-sm ${
        isUser
          ? 'bg-gradient-to-br from-cyan/10 to-blue-500/5 text-primary border border-cyan/15 rounded-tr-md'
          : 'bg-card text-secondary border border-border/80 rounded-tl-md hover:shadow-md'
      }`}>
        {!isUser && message.strategyName && (
          <div className="mb-2">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan/10 border border-cyan/20 text-xs text-cyan">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              {message.strategyName}
            </span>
          </div>
        )}
        {!isUser && message.thinkingSteps && (
          <ThinkingBlock
            steps={message.thinkingSteps}
            expanded={thinkingExpanded}
            onToggle={onToggleThinking}
          />
        )}
        {!isUser ? (
          <div className={MARKDOWN_PROSE_CLASSES}>
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
          </div>
        ) : (
          <div className="text-sm leading-relaxed">
            {message.content.split('\n').map((line, i) => (
              <p key={i} className="mb-1 last:mb-0">{line || '\u00A0'}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble;
