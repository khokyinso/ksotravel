import React from "react";
import { Composition } from "remotion";
import { GreenScreenText } from "./compositions/GreenScreenText";
import { ScriptProps } from "./types";

const defaultProps: ScriptProps = {
  briefId: "japan_001_20260324",
  destination: "japan",
  scriptLines: [
    "Japan Travel Tip #36",
    "If you're planning to visit Japan and thinking about getting a JR Pass — don't buy it yet.",
    "The price went up to $317 USD this year. Unless you're hitting 3+ cities in a week, it's not worth it.",
    "Get a regional pass instead. The Kansai Mini Pass is only $25 for 3 days.",
    "If this helped, follow for more tips. Use code KSOTRAVEL on Klook for 10% off.",
  ],
  seriesTitle: "Japan Travel Tip #36",
  triggerPhrase: "JR PASS",
  brandColor: "#E8272A",
  footageUrl: "",
  targetDuration: 30,
  videoFormat: "green_screen_text",
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="GreenScreenText"
        component={GreenScreenText}
        durationInFrames={30 * 24}
        fps={24}
        width={1080}
        height={1920}
        defaultProps={defaultProps}
        calculateMetadata={({ props }) => ({
          durationInFrames: props.targetDuration * 24,
        })}
      />
    </>
  );
};
