import { useCallback, useEffect, useRef, useState } from 'react';
import type React from 'react';
import { agentApi } from '../api/agent';
import { ApiErrorAlert } from '../components/common';
import { useAgentChatStore } from '../stores/agentChatStore';
import { ChatSidebar } from './chat/components/ChatSidebar';
import { DeleteSessionDialog } from './chat/components/DeleteSessionDialog';
import { MessageBubble } from './chat/components/MessageBubble';
import { LoadingBubble } from './chat/components/LoadingBubble';
import { EmptyChat } from './chat/components/EmptyChat';
import { ChatToolbar } from './chat/components/ChatToolbar';
import { StrategyPicker } from './chat/components/StrategyPicker';
import { ChatComposer } from './chat/components/ChatComposer';
import { useChatStrategies } from './chat/hooks/useChatStrategies';
import { useFollowUpFromQuery } from './chat/hooks/useFollowUpFromQuery';
import type { FollowUpContext, QuickQuestion } from './chat/constants';

const ChatPage: React.FC = () => {
  const [input, setInput] = useState('');
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const followUpContextRef = useRef<FollowUpContext | null>(null);

  const {
    messages, loading, progressSteps, sessionId, sessions, sessionsLoading, chatError,
    loadSessions, loadInitialSession, switchSession, startStream, clearCompletionBadge,
  } = useAgentChatStore();

  const { strategies, selectedStrategy, setSelectedStrategy } = useChatStrategies();
  useFollowUpFromQuery(setInput, followUpContextRef);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, progressSteps]);
  useEffect(() => { clearCompletionBadge(); }, [clearCompletionBadge]);
  useEffect(() => { loadInitialSession(); }, [loadInitialSession]);

  const handleStartNewChat = useCallback(() => {
    followUpContextRef.current = null;
    useAgentChatStore.getState().startNewChat();
    setSidebarOpen(false);
  }, []);

  const handleSwitchSession = useCallback((targetSessionId: string) => {
    switchSession(targetSessionId);
    setSidebarOpen(false);
  }, [switchSession]);

  const confirmDelete = useCallback(() => {
    if (!deleteConfirmId) return;
    agentApi.deleteChatSession(deleteConfirmId).then(() => {
      loadSessions();
      if (deleteConfirmId === sessionId) handleStartNewChat();
    }).catch(() => {});
    setDeleteConfirmId(null);
  }, [deleteConfirmId, sessionId, loadSessions, handleStartNewChat]);

  const handleSend = useCallback(
    async (overrideMessage?: string, overrideStrategy?: string) => {
      const msgText = overrideMessage || input.trim();
      if (!msgText || loading) return;
      const usedStrategy = overrideStrategy || selectedStrategy;
      const usedStrategyName =
        strategies.find((s) => s.id === usedStrategy)?.name ||
        (usedStrategy ? usedStrategy : '通用');

      const payload = {
        message: msgText,
        session_id: sessionId,
        skills: usedStrategy ? [usedStrategy] : undefined,
        context: followUpContextRef.current ?? undefined,
      };
      followUpContextRef.current = null;
      setInput('');
      await startStream(payload, { strategyName: usedStrategyName });
    },
    [input, loading, selectedStrategy, strategies, sessionId, startStream],
  );

  const handleQuickQuestion = (q: QuickQuestion) => {
    setSelectedStrategy(q.strategy);
    handleSend(q.label, q.strategy);
  };

  const toggleThinking = (msgId: string) => {
    setExpandedThinking((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

  const sidebar = (
    <ChatSidebar
      sessions={sessions}
      sessionsLoading={sessionsLoading}
      activeSessionId={sessionId}
      onSelect={handleSwitchSession}
      onDelete={setDeleteConfirmId}
      onNewChat={handleStartNewChat}
    />
  );

  return (
    <div className="h-screen flex flex-col max-w-6xl mx-auto w-full px-6 py-6">
      {/* Hero — aligned with HomePage/SettingsPage (w-14 / text-2xl) */}
      <div className="text-center mb-6 flex-shrink-0">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl
                        bg-gradient-to-br from-purple/15 to-cyan/10 mb-3 shadow-sm">
          <svg className="w-7 h-7 text-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-primary mb-1.5 tracking-tight">AI 问股</h1>
        <p className="text-sm text-secondary max-w-xl mx-auto">
          向 AI 询问个股分析，获取基于策略的交易建议与实时决策报告
        </p>
      </div>

      <div className="flex-1 flex gap-6 min-h-0">
        {/* Desktop sidebar */}
        <div className="hidden md:flex flex-col w-64 flex-shrink-0 glass-card overflow-hidden">
          {sidebar}
        </div>

        {/* Mobile sidebar */}
        {sidebarOpen && (
          <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
            <div className="absolute inset-0 bg-black/60" />
            <div
              className="relative absolute left-0 top-0 bottom-0 w-72 flex flex-col glass-card overflow-hidden border-r border-border shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                className="absolute top-3 right-3 p-2 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition z-10"
                onClick={() => setSidebarOpen(false)}
                aria-label="Close sidebar"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
              {sidebar}
            </div>
          </div>
        )}

        {deleteConfirmId && (
          <DeleteSessionDialog
            onConfirm={confirmDelete}
            onCancel={() => setDeleteConfirmId(null)}
          />
        )}

        {/* Chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 flex flex-col glass-card overflow-hidden min-h-0 relative z-10">
            <ChatToolbar messages={messages} onOpenSidebar={() => setSidebarOpen(true)} />

            <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar relative z-10">
              {messages.length === 0 && !loading ? (
                <EmptyChat onQuickQuestion={handleQuickQuestion} />
              ) : (
                messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    thinkingExpanded={expandedThinking.has(msg.id)}
                    onToggleThinking={() => toggleThinking(msg.id)}
                  />
                ))
              )}
              {loading && <LoadingBubble steps={progressSteps} />}
              <div ref={messagesEndRef} />
            </div>

            <div className="p-4 md:p-6 border-t border-border bg-card relative z-20">
              {chatError && <ApiErrorAlert error={chatError} className="mb-3" />}
              <StrategyPicker
                strategies={strategies}
                selected={selectedStrategy}
                onSelect={setSelectedStrategy}
              />
              <ChatComposer
                input={input}
                setInput={setInput}
                loading={loading}
                onSend={() => handleSend()}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
