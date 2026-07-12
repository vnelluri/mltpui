import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

// `title` stays in the props so pages keep compiling; the topnav no longer
// shows it (pages render their own headings).
export function Layout({ children }: { children: ReactNode; title?: string }) {
  return (
    <div className="flex h-screen flex-col bg-bg-dark">
      <Topbar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto px-6 py-8">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
      <footer className="flex h-9 flex-shrink-0 items-center justify-center border-t border-bg-elevated bg-bg-card text-xs text-text-muted">
        © {new Date().getFullYear()} Truist Financial Corporation. All rights reserved.
      </footer>
    </div>
  );
}
