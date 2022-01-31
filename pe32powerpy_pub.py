#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import time

from pe32me162irpy_pub.pe32me162irpy_pub import Pe32Me162Publisher, main
from pe32sunspecpy_pub.pe32sunspecpy_pub import (
    SUNSPEC_INVERTER_MODEL_ONLY_AC_POWER, SunspecModbusTcpAsyncio)

__version__ = 'pe32powerpy_pub-FIXME'
    
log = logging.getLogger()


class Pe32Me162SunspecPublisherFactory:
    def __init__(self, sunspec_host_port):
        self._sunspec_host_port = sunspec_host_port

    def __call__(self):
        return Pe32Me162SunspecPublisher(self._sunspec_host_port)


class Pe32Me162SunspecPublisher(Pe32Me162Publisher):
    def __init__(self, sunspec_host_port):
        super().__init__()
        self._sunspec_host_port = sunspec_host_port

    async def get_sunspec_power(self):
        reader, writer = await asyncio.open_connection(self._sunspec_host_port)
        c = SunspecModbusTcpAsyncio(reader, writer)
        d = await c.get_from_mapping(SUNSPEC_INVERTER_MODEL_ONLY_AC_POWER)
        return d['I_AC_Power']

    async def _publish(self, pos_act, neg_act, inst_pwr):
        inst_solar_pwr = await self.get_sunspec_power()
        assert inst_pwr.unit == inst_solar_pwr.unit, (inst_pwr, inst_solar_pwr)
        inst_cons_pwr = inst_solar_pwr.__class__(
            inst_solar_pwr + inst_pwr, inst_solar_pwr.unit)
        assert inst_cons_pwr >= 0, (inst_pwr, inst_solar_pwr, inst_cons_pwr)
        log.debug(
            f'_publish: 1.8.0 {pos_act}, 2.8.0 {neg_act}, '
            f'16.7.0 {inst_pwr}, '
            f'S.O.L.A.R {inst_solar_pwr}, C.O.N.S {inst_cons_pwr}')

        tm = int(time.time())
        mqtt_string = (
            f'device_id={self._guid}&'
            f'e_pos_act_energy_wh={int(pos_act)}&'
            f'e_neg_act_energy_wh={int(neg_act)}&'
            f'e_inst_power_w={int(inst_pwr)}&'
            f's_inst_power_w={int(inst_solar_pwr)}&'
            f'c_inst_power_w={int(inst_cons_pwr)}&'
            f'dbg_uptime={tm}&'
            f'dbg_version={__version__}').encode('ascii')

        await self._mqttc.publish(self._mqtt_topic, payload=mqtt_string)

        log.info(
            f'Published: 1.8.0 {pos_act}, 2.8.0 {neg_act}, '
            f'16.7.0 {inst_pwr}, '
            f'S.O.L.A.R {inst_solar_pwr}, C.O.N.S {inst_cons_pwr}')


if __name__ == '__main__':
    called_from_cli = (
        # Reading just JOURNAL_STREAM or INVOCATION_ID will not tell us
        # whether a user is looking at this, or whether output is passed to
        # systemd directly.
        any(os.isatty(i.fileno())
            for i in (sys.stdin, sys.stdout, sys.stderr)) or
        not os.environ.get('JOURNAL_STREAM'))
    sys.stdout.reconfigure(line_buffering=True)  # PYTHONUNBUFFERED, but better
    logging.basicConfig(
        level=(
            logging.DEBUG if os.environ.get('PE32ME162_DEBUG', '')
            else logging.INFO),
        format=(
            '%(asctime)s %(message)s' if called_from_cli
            else '%(message)s'),
        stream=sys.stdout,
        datefmt='%Y-%m-%d %H:%M:%S')

    print(f"pid {os.getpid()}: send SIGINT or SIGTERM to exit.")
    loop = asyncio.get_event_loop()
    publisher_factory = Pe32Me162SunspecPublisherFactory((sys.argv[2], 1502))
    main_coro = main(sys.argv[1], publisher_class=publisher_factory)
    loop.run_until_complete(main_coro)
    loop.close()
    print('end of main')
