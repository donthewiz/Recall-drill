import { DeckItem } from '../../src/types';

// 12 synthetic list cards in the shape of real anatomy lists (written for the
// harness, not copied from any deck): 3-8 comma-separated items of 1-3 words,
// some items with a parenthetical ("true (vertebrosternal)", one holding its
// own commas), some with counts ("2 parietal"), one 19-word answer, and two
// whose front says the order matters ("from superior to inferior", "from
// proximal to distal"). Added with the "Your settings" scoreboard section
// (2026-10-12): list cards are where both the drill time and the misses are,
// and none of shortDeck/mediumDeck/proseDeck is a list.
export const listDeck: DeckItem[] = [
  { front: 'Name the three types of muscle tissue', back: 'skeletal, cardiac, smooth' },
  {
    front: 'List the rib classes by attachment',
    back: 'true (vertebrosternal), false (vertebrochondral), floating (vertebral)',
  },
  {
    front: 'Name the cranial bones with their counts',
    back: '1 frontal, 2 parietal, 2 temporal, 1 occipital, 1 sphenoid, 1 ethmoid',
  },
  {
    front: 'List the regions of the vertebral column from superior to inferior',
    back: 'cervical, thoracic, lumbar, sacral, coccygeal',
  },
  {
    front: 'List the bones of the upper limb from proximal to distal',
    back: 'humerus, radius and ulna, carpals, metacarpals, phalanges',
  },
  {
    front: 'Name the components of a synovial joint',
    back: 'articular cartilage, joint cavity, synovial membrane, fibrous capsule',
  },
  { front: 'Name the four primary tissue types', back: 'epithelial, connective, muscle, nervous' },
  {
    front: 'List the structures of a long bone',
    back: 'diaphysis (central shaft), proximal epiphysis, distal epiphysis, epiphyseal growth plate, articular cartilage, outer fibrous periosteum, medullary cavity (marrow), endosteum',
  },
  { front: 'Name the types of cartilage', back: 'hyaline, elastic, fibrocartilage' },
  {
    front: 'Name the structural classes of joints',
    back: 'fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), synovial joints (freely movable)',
  },
  { front: 'Give the vertebra counts of the upper regions', back: '7 cervical, 12 thoracic, 5 lumbar' },
  {
    front: 'Name the parts of the axial skeleton',
    back: 'skull, hyoid, auditory ossicles, vertebral column, thoracic cage, sternum, ribs',
  },
];
