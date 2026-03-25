/**
 * Decorative empty-state mark for draft / new chat (no copy, SVG-only hero).
 */
export function DraftWelcomeIllustration({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 240 168"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <rect
        x="20"
        y="24"
        width="200"
        height="120"
        rx="18"
        className="stroke-current"
        strokeWidth="1.15"
        opacity={0.22}
      />
      <path
        d="M52 68h96M52 92h136M52 116h72"
        className="stroke-current"
        strokeWidth="2"
        strokeLinecap="round"
        opacity={0.38}
      />
      <path
        d="M176 44c11.046 0 20 8.954 20 20s-8.954 20-20 20-20-8.954-20-20 8.954-20 20-20Z"
        className="stroke-current"
        strokeWidth="1.15"
        opacity={0.28}
      />
      <path
        d="m168.5 63.5 5.2 5.5 11.8-13.2"
        className="stroke-current"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={0.42}
      />
    </svg>
  );
}
