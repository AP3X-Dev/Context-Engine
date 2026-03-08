"use client";

interface ButtonProps {
  children: React.ReactNode;
  href?: string;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
}

export function Button({ children, href, variant = "primary", size = "md" }: ButtonProps) {
  const base = "inline-flex items-center justify-center font-medium rounded-lg transition-all duration-200 cursor-pointer";
  const sizes = {
    sm: "px-4 py-2 text-sm",
    md: "px-6 py-3 text-base",
    lg: "px-8 py-4 text-lg",
  };
  const variants = {
    primary: "bg-gradient-to-r from-[var(--gradient-start)] to-[var(--gradient-end)] text-white hover:opacity-90",
    secondary: "border border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
    ghost: "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
  };

  const className = `${base} ${sizes[size]} ${variants[variant]}`;

  if (href) {
    return <a href={href} className={className}>{children}</a>;
  }
  return <button className={className}>{children}</button>;
}
