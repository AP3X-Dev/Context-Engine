interface SectionProps {
  children: React.ReactNode;
  className?: string;
  id?: string;
}

export function Section({ children, className = "", id }: SectionProps) {
  return (
    <section id={id} className={`px-6 py-24 max-w-6xl mx-auto ${className}`}>
      {children}
    </section>
  );
}
