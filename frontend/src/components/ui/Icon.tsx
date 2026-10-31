import type { SVGProps } from "react";

// A deliberately small, single-weight icon set (1.5px strokes on a 20px grid).
const paths = {
  pin: (
    <>
      <path d="M10 18s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10Z" />
      <circle cx="10" cy="8" r="2.25" />
    </>
  ),
  speaker: (
    <>
      <path d="M3.5 8v4H6l4 3.5v-11L6 8H3.5Z" />
      <path d="M13 7.5a3.5 3.5 0 0 1 0 5M15.5 5a7 7 0 0 1 0 10" />
    </>
  ),
  home: <path d="M3.5 9.5 10 4l6.5 5.5M5 8.5v7.5h10V8.5M8.5 16v-4.5h3V16" />,
  globe: (
    <>
      <circle cx="10" cy="10" r="7.25" />
      <path d="M2.75 10h14.5M10 2.75c2.2 2 3.2 4.5 3.2 7.25s-1 5.25-3.2 7.25c-2.2-2-3.2-4.5-3.2-7.25s1-5.25 3.2-7.25Z" />
    </>
  ),
  landmark: <path d="M3 7.5 10 3.5l7 4M4 7.5h12M5.5 7.5V14m3-6.5V14m3-6.5V14m3-6.5V14M3.5 16.5h13M4.5 14h11" />,
  layers: <path d="m10 3.5 7 3.75-7 3.75-7-3.75 7-3.75ZM3 10.75 10 14.5l7-3.75M3 13.75l7 3.25 7-3.25" />,
  document: <path d="M5 3h6.5L15 6.5V17H5V3Zm6.5 0v3.5H15M7.5 10.5h5m-5 3h5" />,
  checklist: <path d="m3.5 5.5 1.25 1.25L7 4.5m-3.5 6.75L4.75 12.5 7 10.25m-3.5 6.75 1.25 1.25L7 16M10 6h6.5M10 11.75h6.5M10 17h6.5" />,
  scale: <path d="M10 3v14m-4 0h8M4.5 5.5h11M4.5 5.5 2.5 10.5a2 2 0 0 0 4 0l-2-5Zm11 0-2 5a2 2 0 0 0 4 0l-2-5Z" />,
  book: <path d="M10 5.5C8.5 4.2 6 3.75 3.5 4v11.5c2.5-.25 5 .2 6.5 1.5 1.5-1.3 4-1.75 6.5-1.5V4c-2.5-.25-5 .2-6.5 1.5Zm0 0V17" />,
  clock: (
    <>
      <circle cx="10" cy="10" r="7.25" />
      <path d="M10 6v4.25l2.75 1.75" />
    </>
  ),
  person: (
    <>
      <circle cx="10" cy="6.75" r="3.25" />
      <path d="M3.75 16.75c.6-3.2 3-5 6.25-5s5.65 1.8 6.25 5" />
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
