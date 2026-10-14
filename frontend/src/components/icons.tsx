import React from "react";

type IconProps = { size?: number };

const base = (children: React.ReactNode, size = 12) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
    {children}
  </svg>
);

export const DocumentIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M7 3h7l4 4v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
      <path d="M14 3v4h4" />
    </>,
    size
  );

export const SearchIcon = ({ size }: IconProps) =>
  base(
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4-4" />
    </>,
    size
  );

export const BrainIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-1 5.8V15a3 3 0 0 0 3 3h1" />
      <path d="M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 1 5.8V15a3 3 0 0 1-3 3h-1" />
      <path d="M9 4v16M15 4v16" />
    </>,
    size
  );

export const ScissorsIcon = ({ size }: IconProps) =>
  base(
    <>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="6" cy="18" r="2.5" />
      <path d="M8.5 8 20 19M8.5 16 20 5" />
    </>,
    size
  );

export const PencilIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M4 17.5V20h2.5L18.4 8.1a1.4 1.4 0 0 0 0-2L16.9 4.6a1.4 1.4 0 0 0-2 0L4 17.5z" />
    </>,
    size
  );

export const SaveIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <path d="M8 4v5h7V4M8 14h8v6H8z" />
    </>,
    size
  );

export const CheckIcon = ({ size }: IconProps) => base(<path d="M5 12.5l4.5 4.5L19 7" />, size);

export const AlertIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M12 3 2 20h20L12 3z" />
      <path d="M12 10v4M12 17.5h.01" />
    </>,
    size
  );

export const ChevronDownIcon = ({ size }: IconProps) => base(<path d="M6 9l6 6 6-6" />, size);

export const SettingsIcon = ({ size }: IconProps) =>
  base(
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.04 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.96 19.36a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.04H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.64 8.96a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1.04-1.56V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.04 4.6c.6.25 1.3.15 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.25.6.83 1.02 1.56 1.04H21a2 2 0 1 1 0 4h-.09A1.7 1.7 0 0 0 19.4 15z" />
    </>,
    size
  );

export const HistoryIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
      <path d="M12 8v4l3 2" />
    </>,
    size
  );

export const DownloadIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M12 3v12" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 19h16" />
    </>,
    size
  );

export const TrashIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M4 6h16M9 6V4h6v2" />
      <path d="M6 6v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6" />
      <path d="M10 10v6M14 10v6" />
    </>,
    size
  );

export const RefreshIcon = ({ size }: IconProps) =>
  base(
    <>
      <path d="M3 12a9 9 0 0 1 15-6.7" />
      <path d="M21 3v6h-6" />
      <path d="M21 12a9 9 0 0 1-15 6.7" />
      <path d="M3 21v-6h6" />
    </>,
    size
  );

export function iconForEvent(eventType: string, size = 12) {
  if (eventType.includes("brief")) return <DocumentIcon size={size} />;
  if (eventType.includes("search") || eventType.includes("retriev") || eventType.includes("index")) return <SearchIcon size={size} />;
  if (eventType.includes("reason")) return <BrainIcon size={size} />;
  if (eventType.includes("assembl") || eventType.includes("slide") && eventType.includes("draft")) return <PencilIcon size={size} />;
  if (eventType.includes("draft")) return <PencilIcon size={size} />;
  if (eventType.includes("saved") || eventType.includes("complete")) return <SaveIcon size={size} />;
  if (eventType.includes("fail") || eventType.includes("error")) return <AlertIcon size={size} />;
  return <ScissorsIcon size={size} />;
}
