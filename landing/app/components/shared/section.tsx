interface SectionProps {
  children: React.ReactNode;
  className?: string;
  id?: string;
}

export function Section({ children, className = "", id }: SectionProps) {
  return (
    <section id={id} className={`px-8 max-w-[1100px] mx-auto ${className}`} style={{ padding: "80px 32px" }}>
      {children}
    </section>
  );
}
