from __future__ import absolute_import, print_function

import json

import numpy as np
import tensorflow as tf
from gym import spaces

from rltools import log, util
from rltools.algos.policyopt import TRPO, SamplingPolicyOptimizer
from rltools.baselines.linear import LinearFeatureBaseline
from rltools.baselines.mlp import MLPBaseline
from rltools.baselines.zero import ZeroBaseline
from rltools.policy.categorical import CategoricalMLPPolicy
from rltools.policy.gaussian import GaussianGRUPolicy, GaussianMLPPolicy
from rltools.samplers.parallel import ParallelSampler
from rltools.samplers.serial import DecSampler, SimpleSampler


class RLToolsRunner(object):

    def __init__(self, env, args):
        self.args = args
        # XXX
        # Should be handled in the environment?
        # shape mucking is incorrect for image envs
        if args.control == 'centralized':
            obs_space = spaces.Box(
                low=env.agents[0].observation_space.low[0],
                high=env.agents[0].observation_space.high[0],
                shape=(env.agents[0].observation_space.shape[0] * len(env.agents),))
            action_space = spaces.Box(
                low=env.agents[0].observation_space.low[0],
                high=env.agents[0].observation_space.high[0],
                shape=(env.agents[0].action_space.shape[0] * len(env.agents),))
        else:
            obs_space = env.agents[0].observation_space
            action_space = env.agents[0].action_space

        if args.recurrent:
            if args.recurrent == 'gru':
                if isinstance(action_space, spaces.Box):
                    policy = GaussianGRUPolicy(obs_space, action_space,
                                               hidden_spec=args.policy_hidden_spec,
                                               min_stdev=args.min_std, init_logstdev=0.,
                                               enable_obsnorm=args.enable_obsnorm,
                                               state_include_action=False, tblog=args.tblog,
                                               varscope_name='policy')
                elif isinstance(action_space, spaces.Discrete):
                    raise NotImplementedError(args.recurrent)
            else:
                raise NotImplementedError()
        else:
            if isinstance(action_space, spaces.Box):
                policy = GaussianMLPPolicy(obs_space, action_space,
                                           hidden_spec=args.policy_hidden_spec,
                                           min_stdev=args.min_std, init_logstdev=0.,
                                           enable_obsnorm=args.enable_obsnorm, tblog=args.tblog,
                                           varscope_name='policy')
            elif isinstance(action_space, spaces.Discrete):
                policy = CategoricalMLPPolicy(obs_space, action_space,
                                              hidden_spec=args.policy_hidden_spec,
                                              enable_obsnorm=args.enable_obsnorm, tblog=args.tblog,
                                              varscope_name='policy')
            else:
                raise NotImplementedError()

        if args.baseline_type == 'linear':
            baseline = LinearFeatureBaseline(obs_space, enable_obsnorm=args.enable_obsnorm,
                                             varscope_name='baseline')
        elif args.baseline_type == 'mlp':
            baseline = MLPBaseline(obs_space, hidden_spec=args.baseline_hidden_spec,
                                   enable_obsnorm=args.enable_obsnorm,
                                   enable_vnorm=args.enable_vnorm, max_kl=args.max_vf_max_kl,
                                   damping=args.vf_cg_dampoing, time_scale=1. / args.max_traj_len,
                                   varscope_name='baseline')
        elif args.baseline_type == 'zero':
            baseline = ZeroBaseline(obs_space)
        else:
            raise NotImplementedError()

        if args.sampler == 'simple':
            if args.control == 'centralized':
                sampler_cls = SimpleSampler
            elif args.control == 'decentralized':
                sampler_cls = DecSampler
            else:
                raise NotImplementedError()
            sampler_args = dict(max_traj_len=args.max_traj_len, n_timesteps=args.n_timesteps,
                                n_timesteps_min=args.n_timesteps_min,
                                n_timesteps_max=args.n_timesteps_max,
                                timestep_rate=args.timestep_rate, adaptive=args.adaptive_batch)
        elif args.sampler == 'parallel':
            sampler_cls = ParallelSampler
            sampler_args = dict(max_traj_len=args.max_traj_len, n_timesteps=args.n_timesteps,
                                n_timesteps_min=args.n_timesteps_min,
                                n_timesteps_max=args.n_timesteps_max,
                                timestep_rate=args.timestep_rate, adaptive=args.adaptive_batch,
                                enable_rewnorm=args.enable_rewnorm, n_workers=args.sampler_workers,
                                mode=args.control)

        else:
            raise NotImplementedError()

        step_func = TRPO(max_kl=args.max_kl)
        self.algo = SamplingPolicyOptimizer(env=env, policy=policy, baseline=baseline,
                                            step_func=step_func, discount=args.discount,
                                            gae_lambda=args.gae_lambda, sampler_cls=sampler_cls,
                                            sampler_args=sampler_args, n_iter=args.n_iter)

        argstr = json.dumps(vars(args), separators=(',', ':'), indent=2)
        util.header(argstr)
        self.log_f = log.TrainingLog(args.log, [('args', argstr)], debug=args.debug)

    def __call__(self):
        with tf.Session() as sess:
            sess.run(tf.initialize_all_variables())
            self.algo.train(sess, self.log_f, self.args.save_freq)
