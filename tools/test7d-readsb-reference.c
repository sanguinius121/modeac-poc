/* Standalone exhaustive oracle copied faithfully from local readsb mode_ac.c.
 * Source: /usr/local/share/adsb-wiki/readsb-install/git/mode_ac.c
 * Only the pure internalModeAToModeC conversion is included. */
#include <stdio.h>
#define INVALID_ALTITUDE (-9999)
static int readsb_mode_a_to_mode_c(unsigned int ModeA) {
    unsigned int FiveHundreds = 0, OneHundreds = 0;
    if ((ModeA & 0xFFFF8889) != 0 || (ModeA & 0x000000F0) == 0) return INVALID_ALTITUDE;
    if (ModeA & 0x0010) OneHundreds ^= 0x007;
    if (ModeA & 0x0020) OneHundreds ^= 0x003;
    if (ModeA & 0x0040) OneHundreds ^= 0x001;
    if ((OneHundreds & 5) == 5) OneHundreds ^= 2;
    if (OneHundreds > 5) return INVALID_ALTITUDE;
    if (ModeA & 0x0002) FiveHundreds ^= 0x0FF;
    if (ModeA & 0x0004) FiveHundreds ^= 0x07F;
    if (ModeA & 0x1000) FiveHundreds ^= 0x03F;
    if (ModeA & 0x2000) FiveHundreds ^= 0x01F;
    if (ModeA & 0x4000) FiveHundreds ^= 0x00F;
    if (ModeA & 0x0100) FiveHundreds ^= 0x007;
    if (ModeA & 0x0200) FiveHundreds ^= 0x003;
    if (ModeA & 0x0400) FiveHundreds ^= 0x001;
    if (FiveHundreds & 1) OneHundreds = 6 - OneHundreds;
    return (int)(FiveHundreds * 5 + OneHundreds - 13);
}
int main(void) {
    for (unsigned raw=0; raw<=0xFFFF; ++raw) printf("%u,%d\n",raw,readsb_mode_a_to_mode_c(raw));
    return 0;
}
