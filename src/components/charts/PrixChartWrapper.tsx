"use client";
import dynamic from "next/dynamic";

const PrixChart = dynamic(() => import("./PrixChart"), { ssr: false });

interface Props {
  data: Array<{ date: string; valeur: number; devise: string }>;
  couleur?: string;
  titre?: string;
  unite?: string;
  devise?: string;
}

export default function PrixChartWrapper(props: Props) {
  return <PrixChart {...props} />;
}
