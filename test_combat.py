"""Offline CombatAI smoke test against the official recorded observation stream.

Usage: python3 test_combat.py /path/to/mechfight-kit/check/stream.jsonl.gz
Requires combat.py in the same directory. Does not edit my_bot.py or use Docker.
"""
import gzip
import json
import sys
import time

from combat import CombatAI


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 test_combat.py /path/to/stream.jsonl.gz')
    count = 0
    max_ms = 0.0
    total_ms = 0.0
    ai = None
    with gzip.open(sys.argv[1], 'rt', encoding='utf-8') as stream:
        for line in stream:
            message = json.loads(line)
            if message['type'] == 'hello':
                ai = CombatAI(message)
            elif message['type'] == 'obs':
                if ai is None:
                    raise RuntimeError('No hello message before observation')
                start = time.perf_counter()
                result = ai.act(message)
                elapsed = (time.perf_counter() - start) * 1000
                assert isinstance(result, dict), result
                assert set(result).isdisjoint({'tick','move','boost','jump'}), result
                assert len(result.get('fire', [False,False])) == 2, result
                assert all(isinstance(b,bool) for b in result.get('fire', [False,False])), result
                if 'aim' in result:
                    assert len(result['aim']) == 2, result
                json.dumps(result, allow_nan=False)
                count += 1
                max_ms = max(max_ms, elapsed)
                total_ms += elapsed
    print(f'PASS: {count} observations | max computation {max_ms:.3f} ms | mean {total_ms/max(count,1):.3f} ms')
    print('Note: this tests only the combat module on recorded data, not live game score or Docker latency.')


if __name__ == '__main__':
    main()
