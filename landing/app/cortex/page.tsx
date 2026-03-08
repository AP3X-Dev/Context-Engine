import { CortexHero } from "../components/cortex/hero";
import { HowItWorks } from "../components/cortex/how-it-works";
import { Features } from "../components/cortex/features";
import { IdeStrip } from "../components/cortex/ide-strip";
import { Pricing } from "../components/cortex/pricing";
import { FinalCta } from "../components/cortex/final-cta";

export default function CortexHome() {
  return (
    <>
      <CortexHero />
      <HowItWorks />
      <Features />
      <IdeStrip />
      <Pricing />
      <FinalCta />
    </>
  );
}
