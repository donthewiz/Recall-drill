import { runCharacterizationSuite } from './characterization.shared';
import { RealEngineDriver } from './harness/engineDriver';

runCharacterizationSuite(() => new RealEngineDriver());
