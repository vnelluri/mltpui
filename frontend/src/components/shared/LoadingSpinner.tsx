interface LoadingSpinnerProps {
  label?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function LoadingSpinner({ label, size = 'md', className = '' }: LoadingSpinnerProps) {
  const dimensions = size === 'sm' ? 'h-5 w-5' : size === 'lg' ? 'h-10 w-10' : 'h-7 w-7';
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <div
        className={`${dimensions} animate-spin-slow rounded-full border-2 border-brand-purple/30 border-t-brand-purple`}
        role="status"
        aria-label={label ?? 'Loading'}
      />
      {label && <p className="text-sm text-text-secondary">{label}</p>}
    </div>
  );
}
