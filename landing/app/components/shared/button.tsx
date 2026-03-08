"use client";

interface ButtonProps {
  children: React.ReactNode;
  href?: string;
  variant?: "primary" | "white" | "ghost";
  size?: "sm" | "md" | "lg";
}

const sizeStyles = {
  sm: { padding: "8px 18px", fontSize: "14px" },
  md: { padding: "10px 24px", fontSize: "15px" },
  lg: { padding: "14px 32px", fontSize: "16px" },
};

const variantStyles = {
  primary: {
    background: "var(--accent)",
    color: "#0a0a0a",
    border: "none",
    fontWeight: 700,
    boxShadow: "0 4px 20px rgba(0, 212, 106, 0.15), var(--depth-shadow), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.2)",
  },
  white: {
    background: "#fff",
    color: "#0a0a0a",
    border: "none",
    fontWeight: 700,
    boxShadow: "0 0 30px rgba(255, 255, 255, 0.12), var(--depth-shadow), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.15)",
  },
  ghost: {
    background: "none",
    color: "var(--text2)",
    border: "none",
    fontWeight: 500,
    boxShadow: "none",
  },
};

const hoverStyles = {
  primary: {
    background: "var(--accent2)",
    boxShadow: "0 12px 40px rgba(0, 212, 106, 0.4), var(--depth-shadow-hover), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.2)",
  },
  white: {
    background: "#fff",
    boxShadow: "0 0 40px rgba(255, 255, 255, 0.2), var(--depth-shadow-hover), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.15)",
  },
  ghost: {
    background: "none",
    boxShadow: "none",
  },
};

export function Button({ children, href, variant = "primary", size = "md" }: ButtonProps) {
  const sizeS = sizeStyles[size];
  const variantS = variantStyles[variant];
  const hoverS = hoverStyles[variant];

  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: "var(--radius-sm)",
    cursor: "pointer",
    transition: "all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)",
    transform: "translateY(0)",
    ...sizeS,
    ...variantS,
  };

  const handleEnter = (e: React.MouseEvent<HTMLElement>) => {
    const el = e.currentTarget;
    if (variant !== "ghost") {
      el.style.transform = "translateY(-8px)";
      el.style.background = hoverS.background;
      el.style.boxShadow = hoverS.boxShadow;
    } else {
      el.style.color = "var(--text)";
    }
  };

  const handleLeave = (e: React.MouseEvent<HTMLElement>) => {
    const el = e.currentTarget;
    if (variant !== "ghost") {
      el.style.transform = "translateY(0)";
      el.style.background = variantS.background;
      el.style.boxShadow = variantS.boxShadow as string;
    } else {
      el.style.color = "var(--text2)";
    }
  };

  if (href) {
    return (
      <a href={href} style={style} onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
        {children}
      </a>
    );
  }
  return (
    <button style={style} onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
      {children}
    </button>
  );
}
