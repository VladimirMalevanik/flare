import Image from "next/image";

export function BrandMark({
  className = "",
  size = 32,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={["flare-brand-mark", className].filter(Boolean).join(" ")}
      height={size}
      src="/brand/flare-mark.svg"
      unoptimized
      width={size}
    />
  );
}
