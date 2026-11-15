import skylt from "./skylt.svg";

/** The blue TRAINMEET sign. Always scaled as a whole. */
export function Skylt({ className }: { className?: string }) {
  return <img className={className ?? "tm-skylt"} src={skylt} alt="TrainMeet" width={128} height={36} />;
}
