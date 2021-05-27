import gym
import math
import random
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Categorical

from pathlib import Path
import sys
base_dir = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(base_dir))
from env.chooseenv import make

from collections import deque

class Actor(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(Actor, self).__init__()
        self.linear1 = nn.Linear(input_size, hidden_size)
        self.linear2 = nn.Linear(hidden_size, hidden_size)
        self.linear3 = nn.Linear(hidden_size, output_size)

    def forward(self, s):
        x = F.relu(self.linear1(s))
        x = F.relu(self.linear2(x))
        x = F.softmax(self.linear3(x))

        return x


class Critic(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super().__init__()
        self.linear1 = nn.Linear(input_size, hidden_size)
        self.linear2 = nn.Linear(hidden_size, hidden_size)
        self.linear3 = nn.Linear(hidden_size, output_size)

    def forward(self, s, a):
        x = torch.cat([s, a], 1)
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        x = self.linear3(x)

        return x


class Agent(object):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

        s_dim = env.input_dimension.shape[0]
        a_dim = env.action_dim

        self.actor = Actor(s_dim, 256, a_dim)
        self.actor_target = Actor(s_dim, 256, a_dim)
        self.critic = Critic(s_dim + a_dim, 256, a_dim)
        self.critic_target = Critic(s_dim + a_dim, 256, a_dim)
        self.actor_optim = optim.Adam(self.actor.parameters(), lr=self.actor_lr)
        self.critic_optim = optim.Adam(self.critic.parameters(), lr=self.critic_lr)
        self.buffer = []

        self.actor_target.load_state_dict(self.actor.state_dict())
        self.critic_target.load_state_dict(self.critic.state_dict())

        self.learn_step_counter = 0
        self.eps = 0.2

    def act(self, s0):
        if random.random() > self.eps:
            s0 = torch.tensor(s0, dtype=torch.float)
            a0 = self.actor(s0).squeeze(0).detach().numpy()

        else:
            a0 = np.random.uniform(low=0, high=1, size=(2,))

        self.eps *= 0.99999
        self.eps = max(self.eps, 0.05)
        return a0

    def put(self, *transition):
        if len(self.buffer) == self.capacity:
            self.buffer.pop(0)
        self.buffer.append(transition)

    def learn(self):

        if len(self.buffer) < self.batch_size:
            return

        samples = random.sample(self.buffer, self.batch_size)

        s0, a0, r1, s1, done = zip(*samples)

        s0 = torch.tensor(s0, dtype=torch.float)
        a0 = torch.tensor(a0, dtype=torch.float)
        r1 = torch.tensor(r1, dtype=torch.float).view(self.batch_size, -1)
        s1 = torch.tensor(s1, dtype=torch.float)
        done = torch.tensor(done, dtype=torch.float).view(self.batch_size, -1)

        def critic_learn():
            a1 = self.actor_target(s1).detach()
            y_true = r1 + (1 -done) * self.gamma * self.critic_target(s1, a1).detach()

            y_pred = self.critic(s0, a0)

            loss_fn = nn.MSELoss()
            loss = loss_fn(y_pred, y_true)
            self.critic_optim.zero_grad()
            loss.backward()
            self.critic_optim.step()

        def actor_learn():
            loss = -torch.mean(self.critic(s0, self.actor(s0)))
            self.actor_optim.zero_grad()
            loss.backward()
            self.actor_optim.step()

        # self.learn_step_counter += 1
        def soft_update(net_target, net, tau):
            for target_param, param in zip(net_target.parameters(), net.parameters()):
                target_param.data.copy_(target_param.data * (1.0 - tau) + param.data * tau)

        critic_learn()
        actor_learn()
        soft_update(self.critic_target, self.critic, self.tau)
        soft_update(self.actor_target, self.actor, self.tau)

        # if self.learn_step_counter % 100 == 0:
        #     self.critic_target.load_state_dict(self.critic.state_dict())
        #     self.actor_target.load_state_dict(self.actor.state_dict())

def evaluate():
    reward_list = deque(maxlen=10)
    for _ in range(10):
        s0 = env.reset()
        episode_reward = 0
        for step in range(200):
            a0 = agent.act(s0)
            s1, r1, done, _, _ = env.step([a0])
            agent.put(s0, a0, r1, s1)
            episode_reward += r1[0]
            s0 = s1
        reward_list.append(episode_reward)
    return reward_list

def logits2action(logits):
    m = Categorical(torch.Tensor(logits)).sample()
    # print(action)
    # action = np.argmax(logits)
    return [m]

def action_wrapper(joint_action):
    '''
    :param joint_action:
    :return: wrapped joint action: one-hot
    '''
    joint_action_ = []
    for a in range(env.n_player):
        action_a = joint_action[a]
        each = [0] * env.action_dim
        each[action_a] = 1
        action_one_hot = [[each]]
        joint_action_.append([action_one_hot[0][0]])
    return joint_action_

if __name__ == '__main__':

    # classic_Pendulum-v0 or classic_CartPole-v0
    env = make('classic_CartPole-v0')

    env.reset()
    # env.render()

    params = {
        'env': env,
        'gamma': 0.99,
        'actor_lr': 0.0001,
        'critic_lr': 0.0001,
        'tau': 0.02,
        'capacity': 10000,
        'batch_size': 32,
    }

    agent = Agent(**params)
    epi = 0
    while True:
        epi += 1
        s0 = env.reset()
        episode_reward = 0

        for step in range(200):
            a0 = agent.act(s0)
            a = logits2action(a0)
            s1, r1, done, _ , _ = env.step(action_wrapper(a))

            if done:
                r1 = [-1]
            agent.put(s0, a0, r1, s1, done)
            episode_reward += r1[0]
            s0 = s1


            if done:
                agent.learn()
                print('epi: ', epi, 'epi_reward: ', episode_reward, 'eps: ', "%.2f" % agent.eps)
                break


        # if episode_reward > -100:
        #     reward_list = evaluate()
        #     print(np.mean(reward_list))
        #     if np.mean(reward_list) > -200:
        #         torch.save(agent.actor.state_dict(), 'actor_net.pth')
        #         break
