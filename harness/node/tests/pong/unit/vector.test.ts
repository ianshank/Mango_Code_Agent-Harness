/**
 * Vector Unit Tests.
 * Requirement Citations:
 * - R-PONG-CORE-2: 2D vector mathematics and reflection accuracy
 * - C-PONG-GOV-9: High-precision unit testing
 */

import { describe, it, expect } from 'vitest';
import { Vector } from '../../../src/pong/core/vector.js';

describe('Vector Mathematics (R-PONG-CORE-2)', () => {
  it('creates immutable 2D vectors with default and explicit coordinates', () => {
    const v1 = Vector.create();
    expect(v1).toEqual({ x: 0, y: 0 });

    const v2 = Vector.create(10, -5);
    expect(v2).toEqual({ x: 10, y: -5 });
    expect(Object.isFrozen(v2)).toBe(true);
  });

  it('performs vector addition and subtraction correctly', () => {
    const a = Vector.create(3, 4);
    const b = Vector.create(1, 2);

    expect(Vector.add(a, b)).toEqual({ x: 4, y: 6 });
    expect(Vector.subtract(a, b)).toEqual({ x: 2, y: 2 });
  });

  it('scales vectors by scalars and handles non-finite inputs', () => {
    const v = Vector.create(2, -3);
    expect(Vector.scale(v, 2.5)).toEqual({ x: 5, y: -7.5 });
    expect(Vector.scale(v, NaN)).toEqual({ x: 0, y: 0 });
  });

  it('calculates dot products and magnitudes', () => {
    const v = Vector.create(3, 4);
    expect(Vector.magnitude(v)).toBe(5);
    expect(Vector.magnitudeSquared(v)).toBe(25);

    const b = Vector.create(4, 3);
    expect(Vector.dot(v, b)).toBe(24);
  });

  it('normalizes vectors to unit length and handles zero vectors safely', () => {
    const v = Vector.create(0, 10);
    expect(Vector.normalize(v)).toEqual({ x: 0, y: 1 });

    const zero = Vector.create(0, 0);
    expect(Vector.normalize(zero)).toEqual({ x: 0, y: 0 });
  });

  it('reflects incident vectors across surface normals accurately', () => {
    // Ball hitting horizontal top wall (normal pointing down: 0, 1)
    const incident = Vector.create(10, -5);
    const normal = Vector.create(0, 1);
    const reflected = Vector.reflect(incident, normal);
    expect(reflected.x).toBeCloseTo(10);
    expect(reflected.y).toBeCloseTo(5);

    // Ball hitting vertical paddle (normal pointing right: 1, 0)
    const incident2 = Vector.create(-8, 6);
    const normal2 = Vector.create(1, 0);
    const reflected2 = Vector.reflect(incident2, normal2);
    expect(reflected2.x).toBeCloseTo(8);
    expect(reflected2.y).toBeCloseTo(6);
  });

  it('computes distance, clamping, lerp, and angle generation', () => {
    const a = Vector.create(0, 0);
    const b = Vector.create(3, 4);
    expect(Vector.distance(a, b)).toBe(5);

    const clamped = Vector.clamp(Vector.create(-10, 50), 0, 100, 0, 40);
    expect(clamped).toEqual({ x: 0, y: 40 });

    const lerped = Vector.lerp(a, b, 0.5);
    expect(lerped).toEqual({ x: 1.5, y: 2 });

    const fromAng = Vector.fromAngle(0, 10);
    expect(fromAng.x).toBeCloseTo(10);
    expect(fromAng.y).toBeCloseTo(0);
  });
});
