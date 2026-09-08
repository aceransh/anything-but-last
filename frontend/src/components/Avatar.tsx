// No real profile images available from the Sleeper API surface this app
// uses, so this generates a deterministic colored-circle initials avatar
// per name -- the same placeholder-avatar convention GitHub/Slack use.
const AVATAR_COLORS = [
  "#ec4899",
  "#14b8a6",
  "#3b82f6",
  "#f97316",
  "#a855f7",
  "#22c55e",
  "#eab308",
  "#f43f5e",
];

function colorForName(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default function Avatar({
  name,
  size = 32,
}: {
  name: string;
  size?: number;
}) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{
        backgroundColor: colorForName(name),
        width: size,
        height: size,
        fontSize: size * 0.4,
      }}
    >
      {initials(name)}
    </span>
  );
}
