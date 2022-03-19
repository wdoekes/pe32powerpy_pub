#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import sys
import time
from decimal import Decimal

from pe32me162irpy_pub.pe32me162irpy_pub import Pe32Me162Publisher, main
from pe32sunspecpy_pub.pe32sunspecpy_pub import (
    SUNSPEC_INVERTER_MODEL_ONLY_AC_ENERGY_WH,
    SUNSPEC_INVERTER_MODEL_ONLY_AC_POWER,
    DecimalWithUnit,
    SunspecModbusTcpAsyncio)

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

    async def get_sunspec_energy(self):
        for i in (1, 2, 3):
            try:
                inst_solar_energy = await self._get_sunspec_energy()
            except Exception:
                if i == 3:
                    raise
                await asyncio.sleep(1)
            else:
                break
        return inst_solar_energy

    async def get_sunspec_power_estimate(self):
        """If we get only the current Watt usage, we may get a very fluctuating
        snapshot, which additionally always 'leads' the other data, which we
        obtain by difference calculations. Here, we take the average of the
        calculated difference and the current value."""
        pwr_cur = await self.get_sunspec_power()
        pwr_diff = await self.get_sunspec_power_by_diff()
        # diff is always off by a certain margin, but cur is only the current
        # value. Count the diff twice and cur once.
        # (In fact, for a higher t-delta (and a higher value) the diff is more
        # accurate. But for lower t (less than a minute) and lower values (less
        # than 500 W), the cur might be better.)
        avg = Decimal((pwr_cur + pwr_diff + pwr_diff) / 3)
        pwr_est = DecimalWithUnit.with_unit(
            avg.quantize(Decimal('.1')), pwr_cur.unit)
        log.info(f'XXX, got {pwr_cur} and {pwr_diff} averaging to {pwr_est}')
        return pwr_est

    async def get_sunspec_power(self):
        for i in (1, 2, 3):
            try:
                inst_solar_pwr = await self._get_sunspec_power()
            except Exception:
                if i == 3:
                    raise
                await asyncio.sleep(1)
            else:
                break
        return inst_solar_pwr

    async def get_sunspec_power_by_diff(self):
        energy = await self.get_sunspec_energy()
        t = int(time.time() * 1000)
        try:
            self._power_by_diff_energy
        except AttributeError:
            pwr = await self.get_sunspec_power()
        else:
            log.info(f'{t}, {self._power_by_diff_t}')
            td = (t - self._power_by_diff_t)
            log.info(f'{energy}, {self._power_by_diff_energy}')
            energyd = (energy - self._power_by_diff_energy)
            log.info(f'{energyd}, {td}')
            pwr = DecimalWithUnit.with_unit(
                int(energyd * 3600 * 1000 / td), 'W')
            log.info(f'{pwr}')

        self._power_by_diff_t = t
        self._power_by_diff_energy = energy
        return pwr

    async def _get_sunspec_energy(self):
        reader, writer = await asyncio.open_connection(
            *self._sunspec_host_port)
        c = SunspecModbusTcpAsyncio(reader, writer)
        d = await c.get_from_mapping(SUNSPEC_INVERTER_MODEL_ONLY_AC_ENERGY_WH)
        writer.close()
        return d['I_AC_Energy_WH']

    async def _get_sunspec_power(self):
        reader, writer = await asyncio.open_connection(
            *self._sunspec_host_port)
        c = SunspecModbusTcpAsyncio(reader, writer)
        d = await c.get_from_mapping(SUNSPEC_INVERTER_MODEL_ONLY_AC_POWER)
        writer.close()
        return d['I_AC_Power']

    async def _publish(self, pos_act, neg_act, inst_pwr):
        # Very coarse grained values unfortunately :(
        try:
            with open('/run/pe32solaredge_scrape/latest.json') as fp:
                values = json.load(fp)
            if values['last_update'] + 3600 < time.time():
                raise KeyError('latest.json is too old')
            solar_act = DecimalWithUnit.with_unit(
                int(values['solar_act']), pos_act.unit)
            inst_solar_pwr = DecimalWithUnit.with_unit(
                int(values['inst_solar_pwr']), inst_pwr.unit)
            del values
        except (FileNotFoundError, KeyError) as e:
            log.error('no coarse grained fallback values (%r, %s)', e, e)
            solar_act = None  # None instead of 0 if we have no values..
            inst_solar_pwr = DecimalWithUnit.with_unit(
                max(-inst_pwr, 0), inst_pwr.unit)

        try:
            inst_solar_pwr = await self.get_sunspec_power_estimate()
        except ConnectionRefusedError as e:
            # [Errno 111] Connect call failed ('1.2.3.4', 1502)
            log.error('connection refused, only poor values (%r, %s)', e, e)
        except OSError as e:
            # [Errno 113] Connect call failed ('1.2.3.4', 1502)
            log.error('connection timeout, only poor values (%r, %s)', e, e)

        # Check and fix up values.
        assert inst_pwr.unit == inst_solar_pwr.unit, (inst_pwr, inst_solar_pwr)
        inst_cons_pwr = DecimalWithUnit.with_unit(
            inst_solar_pwr + inst_pwr, inst_solar_pwr.unit)
        if inst_cons_pwr < 0:
            # assert inst_cons_pwr >= 0, (
            #   inst_pwr, inst_solar_pwr, inst_cons_pwr)
            inst_solar_pwr = DecimalWithUnit.with_unit(
                inst_solar_pwr - inst_cons_pwr, inst_solar_pwr.unit)
            inst_cons_pwr = DecimalWithUnit.with_unit(0, inst_pwr.unit)

        log.debug(
            f'_publish: 1.8.0 {pos_act}, 2.8.0 {neg_act}, '
            f'solar_act {solar_act}, '
            f'16.7.0 {inst_pwr}, '
            f'S.O.L.A.R {inst_solar_pwr}, C.O.N.S {inst_cons_pwr}')
        await self._publish_with_solar(
            pos_act, neg_act, solar_act, inst_pwr, inst_solar_pwr,
            inst_cons_pwr)

    async def _publish_with_solar(
            self, pos_act, neg_act, solar_act,
            inst_pwr, inst_solar_pwr, inst_cons_pwr):

        tm = int(time.time())
        solar_act_if_available = (
            f's_act_energy_wh={int(solar_act)}&' if solar_act else '')
        mqtt_string = (
            f'device_id={self._guid}&'
            f'e_pos_act_energy_wh={int(pos_act)}&'
            f'e_neg_act_energy_wh={int(neg_act)}&'
            f'{solar_act_if_available}'
            f'e_inst_power_w={int(inst_pwr)}&'
            f's_inst_power_w={int(inst_solar_pwr)}&'
            f'c_inst_power_w={int(inst_cons_pwr)}&'
            f'dbg_uptime={tm}&'
            f'dbg_version={__version__}').encode('ascii')

        await self._mqtt_publish(self._mqtt_topic, payload=mqtt_string)

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
