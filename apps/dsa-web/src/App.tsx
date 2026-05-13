import type React from 'react';
import { useEffect } from 'react';
import {BrowserRouter as Router, Routes, Route, NavLink, useLocation, Navigate} from 'react-router-dom';
import HomePage from './pages/HomePage';
import BacktestPage from './pages/BacktestPage';
import SettingsPage from './pages/SettingsPage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
import ChatPage from './pages/ChatPage';
import PickerPage from './pages/PickerPage';
import PickerHistoryDetailPage from './pages/PickerHistoryDetailPage';
import { ApiErrorAlert, Spinner } from './components/common';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useAgentChatStore } from './stores/agentChatStore';
import { useTheme } from './hooks/useTheme';
import './App.css';

// Navigation icons (w-5 h-5)
const HomeIcon: React.FC<{ active?: boolean }> = ({active}) => (
    <svg className="w-5 h-5" fill={active ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
    </svg>
);

const BacktestIcon: React.FC<{ active?: boolean }> = ({active}) => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={active ? 2 : 1.5}
              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
    </svg>
);

const SettingsIcon: React.FC<{ active?: boolean }> = ({active}) => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={active ? 2 : 1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
    </svg>
);

const ChatIcon: React.FC<{ active?: boolean }> = ({active}) => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={active ? 2 : 1.5}
              d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
    </svg>
);

const PickerIcon: React.FC<{ active?: boolean }> = ({active}) => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={active ? 2 : 1.5}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
    </svg>
);

const LogoutIcon: React.FC = () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
    </svg>
);

const MoonIcon: React.FC = () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/>
    </svg>
);

const SunIcon: React.FC = () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/>
    </svg>
);

type DockItem = {
    key: string;
    label: string;
    to: string;
    icon: React.FC<{ active?: boolean }>;
};

const NAV_ITEMS: DockItem[] = [
    {
        key: 'home',
        label: '首页',
        to: '/',
        icon: HomeIcon,
    },
    {
        key: 'chat',
        label: '问股',
        to: '/chat',
        icon: ChatIcon,
    },
    {
        key: 'picker',
        label: '选股',
        to: '/picker',
        icon: PickerIcon,
    },
    {
        key: 'backtest',
        label: '回测',
        to: '/backtest',
        icon: BacktestIcon,
    },
];

// Sidebar tooltip component
const NavTooltip: React.FC<{ label: string }> = ({label}) => (
    <div className="absolute left-full ml-3 top-1/2 -translate-y-1/2 opacity-0 scale-95 pointer-events-none group-hover:opacity-100 group-hover:scale-100 transition-all duration-150 z-50">
        <div className="relative bg-gray-900 text-gray-100 text-[11px] font-medium px-2.5 py-1.5 rounded-lg shadow-xl ring-1 ring-white/[0.06] whitespace-nowrap">
            <div className="absolute right-full top-1/2 -translate-y-1/2 border-[4px] border-transparent border-r-gray-900"/>
            {label}
        </div>
    </div>
);

// Sidebar nav item
const SideNavItem: React.FC<{
    item: DockItem;
    badge?: boolean;
}> = ({item, badge}) => {
    const Icon = item.icon;
    return (
        <NavLink
            to={item.to}
            end={item.to === '/'}
            className="relative group"
        >
            {({isActive}) => (
                <>
                    {/* Active indicator - left edge glow bar */}
                    {isActive && (
                        <span className="absolute -left-[1px] top-1/2 -translate-y-1/2 w-[2px] h-4 rounded-full bg-blue-400 shadow-[0_0_6px_rgba(96,165,250,0.6)]"/>
                    )}
                    <div
                        className={`w-10 h-10 rounded-xl flex items-center justify-center relative transition-all duration-200 ${
                            isActive
                                ? 'text-white bg-white/[0.08] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                                : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.04]'
                        }`}
                    >
                        <Icon active={isActive}/>
                        {badge && (
                            <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-blue-400 shadow-[0_0_4px_rgba(96,165,250,0.8)]"/>
                        )}
                    </div>
                    <NavTooltip label={item.label}/>
                </>
            )}
        </NavLink>
    );
};

// Desktop side navigation
const SideNav: React.FC = () => {
    const {authEnabled, logout} = useAuth();
    const completionBadge = useAgentChatStore((s) => s.completionBadge);
    const { dark, toggle: toggleTheme } = useTheme();

    return (
        <aside className="fixed left-0 top-0 h-screen w-[68px] z-50 hidden md:flex flex-col items-center bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 border-r border-white/[0.06]">
            {/* Logo */}
            <div className="pt-5 pb-4">
                <NavLink to="/" title="首页">
                    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
                        <svg className="w-4.5 h-4.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                                  d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                        </svg>
                    </div>
                </NavLink>
            </div>
            {/* Separator */}
            <div className="w-8 h-px bg-white/[0.06] mb-3"/>

            {/* Main nav items */}
            <nav className="flex flex-col items-center gap-1.5" aria-label="主导航">
                {NAV_ITEMS.map((item) => (
                    <SideNavItem
                        key={item.key}
                        item={item}
                        badge={item.key === 'chat' && completionBadge}
                    />
                ))}
            </nav>

            {/* Spacer */}
            <div className="flex-1"/>

            {/* Bottom: Theme toggle + Settings + Logout */}
            <div className="w-8 h-px bg-white/[0.06] mb-2"/>
            <div className="flex flex-col items-center gap-1.5 pb-4">
                {/* Dark mode toggle */}
                <div className="relative group">
                    <button
                        type="button"
                        onClick={toggleTheme}
                        className="w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 text-slate-500 hover:text-slate-300 hover:bg-white/[0.04]"
                        aria-label={dark ? '切换亮色模式' : '切换暗色模式'}
                    >
                        {dark ? <SunIcon/> : <MoonIcon/>}
                    </button>
                    <NavTooltip label={dark ? '亮色模式' : '暗色模式'}/>
                </div>

                <NavLink
                    to="/settings"
                    className="relative group"
                >
                    {({isActive}) => (
                        <>
                            {isActive && (
                                <span className="absolute -left-[1px] top-1/2 -translate-y-1/2 w-[2px] h-4 rounded-full bg-blue-400 shadow-[0_0_6px_rgba(96,165,250,0.6)]"/>
                            )}
                            <div
                                className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 ${
                                    isActive
                                        ? 'text-white bg-white/[0.08] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                                        : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.04]'
                                }`}
                            >
                                <SettingsIcon active={isActive}/>
                            </div>
                            <NavTooltip label="设置"/>
                        </>
                    )}
                </NavLink>

                {authEnabled && (
                    <div className="relative group">
                        <button
                            type="button"
                            onClick={() => logout()}
                            className="w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 text-slate-500 hover:text-red-400 hover:bg-red-500/[0.08]"
                        >
                            <LogoutIcon/>
                        </button>
                        <NavTooltip label="退出登录"/>
                    </div>
                )}
            </div>
        </aside>
    );
};

// Mobile bottom tab bar
const MobileBottomTab: React.FC = () => {
    const {authEnabled, logout} = useAuth();
    const completionBadge = useAgentChatStore((s) => s.completionBadge);

    const allItems: (DockItem | { key: string; label: string; to: string; icon: React.FC<{ active?: boolean }> })[] = [
        ...NAV_ITEMS,
        {key: 'settings', label: '设置', to: '/settings', icon: SettingsIcon},
    ];

    return (
        <nav className="fixed bottom-0 left-0 right-0 z-50 h-14 bg-white dark:bg-slate-900 border-t border-gray-200 dark:border-slate-700 flex md:hidden items-center justify-around px-2" aria-label="移动端导航">
            {allItems.map((item) => {
                const Icon = item.icon;
                return (
                    <NavLink
                        key={item.key}
                        to={item.to}
                        end={item.to === '/'}
                        className={({isActive}) =>
                            `flex flex-col items-center justify-center gap-0.5 px-2 py-1 rounded-lg transition-colors ${
                                isActive
                                    ? 'text-cyan'
                                    : 'text-gray-400'
                            }`
                        }
                    >
                        {({isActive}) => (
                            <>
                                <div className="relative">
                                    <Icon active={isActive}/>
                                    {item.key === 'chat' && completionBadge && (
                                        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-cyan"/>
                                    )}
                                </div>
                                <span className="text-[10px] font-medium">{item.label}</span>
                            </>
                        )}
                    </NavLink>
                );
            })}
            {authEnabled && (
                <button
                    type="button"
                    onClick={() => logout()}
                    className="flex flex-col items-center justify-center gap-0.5 px-2 py-1 rounded-lg text-gray-400 transition-colors active:text-red-500"
                >
                    <LogoutIcon/>
                    <span className="text-[10px] font-medium">退出</span>
                </button>
            )}
        </nav>
    );
};

const AppContent: React.FC = () => {
    const location = useLocation();
    const { authEnabled, loggedIn, isLoading, loadError, refreshStatus } = useAuth();

    useEffect(() => {
        useAgentChatStore.getState().setCurrentRoute(location.pathname);
    }, [location.pathname]);

    if (isLoading) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-base">
                <Spinner size="lg" />
            </div>
        );
    }

    if (loadError) {
        return (
            <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-base px-4">
                <div className="w-full max-w-lg">
                    <ApiErrorAlert error={loadError}/>
                </div>
                <button
                    type="button"
                    className="btn-primary"
                    onClick={() => void refreshStatus()}
                >
                    重试
                </button>
            </div>
        );
    }

    if (authEnabled && !loggedIn) {
        if (location.pathname === '/login') {
            return <LoginPage />;
        }
        const redirect = encodeURIComponent(location.pathname + location.search);
        return <Navigate to={`/login?redirect=${redirect}`} replace />;
    }

    if (location.pathname === '/login') {
        return <Navigate to="/" replace />;
    }

    return (
        <div className="flex flex-col min-h-screen bg-base">
            <SideNav/>
            <MobileBottomTab/>
            <main className="flex-1 md:pl-[68px] pb-14 md:pb-0">
                <Routes>
                    <Route path="/" element={<HomePage/>}/>
                    <Route path="/chat" element={<ChatPage/>}/>
                    <Route path="/picker" element={<PickerPage/>}/>
                    <Route path="/picker/history/:id" element={<PickerHistoryDetailPage/>}/>
                    <Route path="/backtest" element={<BacktestPage/>}/>
                    <Route path="/settings" element={<SettingsPage/>}/>
                    <Route path="/login" element={<LoginPage/>}/>
                    <Route path="*" element={<NotFoundPage/>}/>
                </Routes>
            </main>
        </div>
    );
};

const App: React.FC = () => {
    return (
        <Router>
            <AuthProvider>
                <AppContent/>
            </AuthProvider>
        </Router>
    );
};

export default App;
