import { runCharacterizationSuite } from './characterization.shared';
import { LegacyEngine } from './reference/legacyEngine';

runCharacterizationSuite(() => new LegacyEngine());
