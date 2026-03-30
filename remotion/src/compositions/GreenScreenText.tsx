import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";
import { ScriptProps } from "../types";

const BRAND_COLORS: Record<string, string> = {
  japan: "#E8272A",
  greece: "#0D5EAF",
  italy: "#009246",
  korea: "#00A693",
  thailand: "#FFB400",
  mexico: "#006847",
  portugal: "#006600",
  spain: "#AA151B",
  france: "#002395",
  turkey: "#E30A17",
  poland: "#DC143C",
  china: "#DE2910",
};

const TextBlock: React.FC<{
  text: string;
  isTitle: boolean;
  isCta: boolean;
  brandColor: string;
  appearFrame: number;
}> = ({ text, isTitle, isCta, brandColor, appearFrame }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Not visible yet
  if (frame < appearFrame) return null;

  const localFrame = frame - appearFrame;

  const slideUp = spring({
    frame: localFrame,
    fps,
    config: { damping: 20, stiffness: 100 },
  });

  const opacity = interpolate(localFrame, [0, 8], [0, 1], {
    extrapolateRight: "clamp",
  });

  const translateY = interpolate(slideUp, [0, 1], [30, 0]);

  const bgColor = isCta
    ? brandColor
    : isTitle
    ? "rgba(0, 0, 0, 0.85)"
    : "rgba(0, 0, 0, 0.7)";

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${translateY}px)`,
        backgroundColor: bgColor,
        borderRadius: 12,
        padding: isTitle ? "14px 24px" : "12px 20px",
        marginBottom: 10,
        marginLeft: 40,
        marginRight: 40,
      }}
    >
      <p
        style={{
          color: "white",
          fontSize: isTitle ? 46 : 40,
          fontWeight: isTitle ? 800 : 600,
          fontFamily: "Helvetica, Arial, sans-serif",
          lineHeight: 1.35,
          margin: 0,
          textShadow: "1px 1px 3px rgba(0,0,0,0.5)",
          wordWrap: "break-word",
        }}
      >
        {text}
      </p>
    </div>
  );
};

export const GreenScreenText: React.FC<ScriptProps> = ({
  scriptLines,
  triggerPhrase,
  brandColor,
  footageUrl,
  destination,
  targetDuration,
}) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const color = brandColor || BRAND_COLORS[destination] || "#FFFFFF";

  // Calculate stagger: evenly space blocks across video duration
  const totalBlocks = scriptLines.length;
  const staggerFrames = Math.floor(
    ((targetDuration * fps) - fps * 2) / Math.max(totalBlocks, 1)
  );

  // Only render blocks that are currently visible
  const visibleLines = scriptLines.filter((_, i) => {
    const appearFrame = i * staggerFrames;
    return frame >= appearFrame;
  });

  return (
    <AbsoluteFill>
      {/* Background footage */}
      {footageUrl ? (
        <OffthreadVideo
          src={
            footageUrl.startsWith("http")
              ? footageUrl
              : staticFile(footageUrl)
          }
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          volume={0}
        />
      ) : (
        <AbsoluteFill style={{ backgroundColor: "#141420" }} />
      )}

      {/* Dark gradient overlay for text readability */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, transparent 20%, rgba(0,0,0,0.2) 40%, rgba(0,0,0,0.6) 100%)",
        }}
      />

      {/* Text blocks — bottom-aligned, grow upward */}
      <div
        style={{
          position: "absolute",
          bottom: 180,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
        }}
      >
        {scriptLines.map((line, i) => {
          const appearFrame = i * staggerFrames;
          const isLastTwo =
            i === scriptLines.length - 1 || i === scriptLines.length - 2;
          const isCta =
            isLastTwo &&
            triggerPhrase &&
            line.toLowerCase().includes(triggerPhrase.toLowerCase());
          const isTitle = i === 0;

          return (
            <TextBlock
              key={i}
              text={line}
              isTitle={isTitle}
              isCta={isCta}
              brandColor={color}
              appearFrame={appearFrame}
            />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
