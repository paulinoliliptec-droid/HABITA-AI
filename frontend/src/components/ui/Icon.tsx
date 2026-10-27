import type { SVGProps } from "react";

// A deliberately small, single-weight icon set (1.5px strokes on a 20px grid).
const paths = {
  pin: (
    <>
      <path d="M10 18s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10Z" />
      <circle cx="10" cy="8" r="2.25" />
    </>
  ),
  arrowRight: <path d="M4 10h12m-5-5 5 5-5 5" />,
  arrowLeft: <path d="M16 10H4m5-5-5 5 5 5" />,
  copy: (
    <>
      <rect x="7" y="7" width="9" height="9" rx="1.5" />
      <path d="M13 4.5V4a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h.5" />
    </>
  ),
  check: <path d="m4.5 10.5 3.5 3.5 7.5-8" />,
  alert: (
    <>
      <path d="M10 6.5v4.5" />
      <circle cx="10" cy="13.75" r=".6" fill="currentColor" stroke="none" />
      <path d="M8.7 3.2 2.4 14.5A1.5 1.5 0 0 0 3.7 16.7h12.6a1.5 1.5 0 0 0 1.3-2.2L11.3 3.2a1.5 1.5 0 0 0-2.6 0Z" />
    </>
  ),
  info: (
    <>
      <circle cx="10" cy="10" r="7.25" />
      <path d="M10 9v4.5" />
      <circle cx="10" cy="6.5" r=".6" fill="currentColor" stroke="none" />
    </>
  ),
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 20, ...props }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
