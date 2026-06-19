"use client";
import { LineChart, Line, ResponsiveContainer, Tooltip } from "recharts";

interface MiniSparklineProps {
  data: number[];
  couleur?: string;
  height?: number;
}

export default function MiniSparkline({ data, couleur = "#92BA59", height = 40 }: MiniSparklineProps) {
  const chartData = data.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData}>
        <Tooltip
          content={() => null}
          cursor={false}
        />
        <Line
          type="monotone"
          dataKey="v"
          stroke={couleur}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
