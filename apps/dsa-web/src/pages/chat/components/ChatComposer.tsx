import type React from 'react';

export interface ChatComposerProps {
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  onSend: () => void;
}

export const ChatComposer: React.FC<ChatComposerProps> = ({ input, setInput, loading, onSend }) => {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="flex gap-3 items-end">
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="例如：分析 600519 / 茅台现在适合买入吗？ (Enter 发送, Shift+Enter 换行)"
        disabled={loading}
        rows={1}
        className="input-terminal flex-1 min-h-[44px] max-h-[200px] py-2.5 resize-none"
        style={{ height: 'auto' }}
        onInput={(e) => {
          const t = e.target as HTMLTextAreaElement;
          t.style.height = 'auto';
          t.style.height = `${Math.min(t.scrollHeight, 200)}px`;
        }}
      />
      <button
        onClick={onSend}
        disabled={!input.trim() || loading}
        className="btn-primary h-[44px] px-6 flex-shrink-0 flex items-center justify-center gap-2"
      >
        {loading ? (
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        ) : (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        )}
        发送
      </button>
    </div>
  );
};

export default ChatComposer;
