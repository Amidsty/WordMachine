import { z } from 'zod'

export const multiplierSchema = z.string().regex(/^(?:0\.[1-9][0-9]|[1-4]\.[0-9]{2}|5\.00)$/)
export const perfPolicyFields = {
  // Compatibility multiplier-policy family; individual answers retain their own versions.
  perf_rule_version: z.enum(['legacy-v1', 'dict-perf-v1']).optional(),
  next_answer_perf_rule_version: z
    .enum(['perf-v2', 'dict-perf-v2', 'weighted-perf-v1', 'weighted-perf-v2'])
    .nullable()
    .optional(),
  multiplier_snapshot: multiplierSchema.nullable().optional(),
}

export const userSchema = z.object({
  id: z.number().int().positive(),
  username: z.string().min(1),
  introduction: z.string().nullable(),
  rating: z.number().finite().nullable(),
  type: z.string().nullable(),
  admin_level: z.number().int().min(0).max(5).optional(),
})

export const authenticatedSessionSchema = z.object({
  success: z.literal(true),
  authenticated: z.literal(true),
  user: userSchema,
  csrf_token: z.string().min(1).max(256),
})

export const sessionSchema = z.discriminatedUnion('authenticated', [
  authenticatedSessionSchema,
  z.object({
    success: z.literal(true),
    authenticated: z.literal(false),
    user: z.null(),
    csrf_token: z.string().min(1).max(256),
  }),
])

export const successSchema = z.object({ success: z.literal(true) })
export const registrationSchema = successSchema.extend({ uid: z.number().int().positive() })
export const profileSchema = successSchema.extend({ reauthenticate: z.boolean(), user: userSchema })
export const errorSchema = z.object({
  success: z.literal(false),
  code: z.string(),
  message: z.string(),
  details: z.unknown().optional(),
})

export type Session = z.infer<typeof sessionSchema>
export type PublicUser = z.infer<typeof userSchema>
