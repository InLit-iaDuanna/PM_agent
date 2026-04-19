"use client";

import { useEffect, useMemo, useState } from "react";

import { TREND_CATEGORY_ORDER, TREND_CATEGORY_TINTS } from "../data/trend-types";

const FACE_ROTATIONS: Record<number, { x: number; y: number }> = {
  1: { x: 0, y: 0 },
  2: { x: 0, y: -90 },
  3: { x: 0, y: -180 },
  4: { x: 0, y: 90 },
  5: { x: -90, y: 0 },
  6: { x: 90, y: 0 },
};

const INITIAL_TRANSFORM = "rotateX(-18deg) rotateY(28deg)";

interface TrendDiceProps {
  targetFace: number;
  onRollComplete: () => void;
  isRolled: boolean;
}

export function TrendDice({ targetFace, onRollComplete, isRolled }: TrendDiceProps) {
  const [transform, setTransform] = useState(INITIAL_TRANSFORM);
  const [isAnimating, setIsAnimating] = useState(false);

  const faces = useMemo(
    () =>
      TREND_CATEGORY_ORDER.map((label, index) => ({
        face: index + 1,
        label,
      })),
    [],
  );

  useEffect(() => {
    if (!isRolled) {
      setIsAnimating(false);
      setTransform(INITIAL_TRANSFORM);
      return;
    }
    const rotation = FACE_ROTATIONS[targetFace] ?? FACE_ROTATIONS[1];
    const extraX = 720 + Math.floor(Math.random() * 4) * 180;
    const extraY = 900 + Math.floor(Math.random() * 4) * 180;
    setIsAnimating(true);
    setTransform(`rotateX(${rotation.x + extraX}deg) rotateY(${rotation.y + extraY}deg)`);
    const timer = window.setTimeout(() => {
      setIsAnimating(false);
      onRollComplete();
    }, 1250);
    return () => window.clearTimeout(timer);
  }, [isRolled, onRollComplete, targetFace]);

  return (
    <div className="flex flex-col items-center gap-5">
      <div className="dice-scene">
        <div
          className="dice-cube"
          style={{
            transform,
            transition: isAnimating ? "transform 1.2s cubic-bezier(0.34, 1.56, 0.64, 1)" : "transform 360ms ease-out",
          }}
        >
          {faces.map((item) => (
            <div
              key={item.face}
              className={`dice-face face-${item.face}`}
              style={{ background: `linear-gradient(180deg, rgba(255,255,255,0.95), ${TREND_CATEGORY_TINTS[item.label]})` }}
            >
              <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-full border border-[color:var(--border-soft)] bg-white/70 text-sm font-semibold text-[color:var(--ink)]">
                {item.face}
              </div>
              <p className="text-base font-semibold tracking-[-0.03em] text-[color:var(--ink)]">{item.label}</p>
              <p className="mt-2 text-center text-xs leading-5 text-[color:var(--muted)]">今日设计方向由这一面决定</p>
            </div>
          ))}
        </div>
      </div>

      <style jsx>{`
        .dice-scene {
          width: 180px;
          height: 180px;
          perspective: 720px;
        }
        .dice-cube {
          width: 100%;
          height: 100%;
          position: relative;
          transform-style: preserve-3d;
          will-change: transform;
        }
        .dice-face {
          position: absolute;
          width: 180px;
          height: 180px;
          border-radius: var(--r-lg);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 18px;
          backface-visibility: hidden;
          border: 1px solid var(--border-soft);
          box-shadow: var(--shadow-md);
          backdrop-filter: blur(16px);
        }
        .face-1 { transform: rotateY(0deg) translateZ(90px); }
        .face-2 { transform: rotateY(90deg) translateZ(90px); }
        .face-3 { transform: rotateY(180deg) translateZ(90px); }
        .face-4 { transform: rotateY(-90deg) translateZ(90px); }
        .face-5 { transform: rotateX(90deg) translateZ(90px); }
        .face-6 { transform: rotateX(-90deg) translateZ(90px); }
      `}</style>
    </div>
  );
}
