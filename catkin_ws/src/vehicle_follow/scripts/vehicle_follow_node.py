#!/usr/bin/env python
import rospy
import numpy as np
import math
from std_msgs.msg import Bool
from duckietown_msgs.msg import Twist2DStamped, VehiclePose
from sensor_msgs.msg import Joy


class VehicleFollow(object):
    def __init__(self):
        self.node_name = rospy.get_name()
        self.last_vehicle_pose = VehiclePose()

        self.car_cmd_msg = Twist2DStamped()
        self.car_cmd_msg.omega = 0.0
        self.car_cmd_msg.v = 0.0

        # self.pub_counter = 1

        self.last_omega = 0
        self.last_v = 0

        # Setup parameters
        self.dist_ref = self.setup_parameter("~dist_ref", 0.15)
        self.head_ref = self.setup_parameter("~head_ref", 0.0)
        self.k_follow = self.setup_parameter("~k_follow", 1.0)  # Linear velocity
        self.k_heading = self.setup_parameter("~k_heading", 1.0)  # P gain for theta

        self.head_thres = self.setup_parameter("~head_thres", math.pi / 4)  # Maximum desired heading
        self.max_speed = self.setup_parameter("~max_speed", 0.4)
        self.max_heading = self.setup_parameter("~max_heading", 0.2)
        self.deadspace_speed = self.setup_parameter("~deadspace_speed", 0.05)
        self.deadspace_heading = self.setup_parameter("~deadspace_heading", 0.2)

        # Publication
        self.pub_car_cmd = rospy.Publisher("~car_cmd", Twist2DStamped, queue_size=1)

        # Subscriptions
        self.sub_target_pose = rospy.Subscriber("~target_pose", VehiclePose, self.cb_pose, queue_size=1)

        self.params_update = rospy.Timer(rospy.Duration.from_sec(1.0), self.update_params_event)

        # safe shutdown
        rospy.on_shutdown(self.custom_shutdown)

        # timer
        rospy.loginfo("[%s] Initialized " % (rospy.get_name()))

    def setup_parameter(self, param_name, default_value):
        value = rospy.get_param(param_name, default_value)
        rospy.set_param(param_name, value)  # Write to parameter server for transparancy
        rospy.loginfo("[%s] %s = %s " % (self.node_name, param_name, value))
        return value

    def update_params_event(self, event):
        params_old = (self.dist_ref, self.head_ref, self.k_follow, self.k_heading, self.head_thres, self.max_speed, self.max_heading, self.deadspace_speed, self.deadspace_heading)

        dist_ref = rospy.get_param("~dist_ref")
        head_ref = rospy.get_param("~head_ref")
        k_follow = rospy.get_param("~k_follow")
        k_heading = rospy.get_param("~k_heading")
        head_thres = rospy.get_param("~head_thres")
        max_speed = rospy.get_param("~max_speed")
        max_heading = rospy.get_param("~max_heading")
        deadspace_speed = rospy.get_param("~deadspace_speed")
        deadspace_heading = rospy.get_param("~deadspace_heading")

        params_new = (dist_ref, head_ref, k_follow, k_heading, head_thres, max_speed, max_heading, deadspace_speed, deadspace_heading)

        if params_old != params_new:
            rospy.loginfo("[%s] Gains changed." % self.node_name)
            rospy.loginfo(
                "old: dist_ref %f, head_ref %f, k_follow %f, k_heading %f, head_thres %f, max_speed %f, max_heading %f, deadspace_speed %f , deadspace_heading %f " % params_old)
            rospy.loginfo(
                "new: dist_ref %f, head_ref %f, k_follow %f, k_heading %f, head_thres %f, max_speed %f, max_heading %f, deadspace_speed %f , deadspace_heading %f" % params_new)
            self.dist_ref = dist_ref
            self.head_ref = head_ref
            self.k_follow = k_follow
            self.k_heading = k_heading
            self.head_thres = head_thres
            self.max_speed = max_speed
            self.max_heading = max_heading
            self.deadspace_speed = deadspace_speed
            self.deadspace_heading = deadspace_heading

    def custom_shutdown(self):
        rospy.loginfo("[%s] Shutting down..." % self.node_name)

        # Stop listening
        self.sub_target_pose.unregister()

        # Send stop command to car command switch
        self.car_cmd_msg.v = 0.0
        self.car_cmd_msg.omega = 0.0
        self.pub_car_cmd.publish(self.car_cmd_msg)

        rospy.sleep(0.5)  # To make sure that it gets published.
        rospy.loginfo("[%s] Shutdown" % self.node_name)

    def cb_pose(self, vehicle_pose_msg):

        if not vehicle_pose_msg.detection:
            # it stops if it doesnt see
            # copy message header over:
            self.car_cmd_msg.header = vehicle_pose_msg.header
            self.car_cmd_msg.v = 0.0
            self.car_cmd_msg.omega = 0.0
            self.pub_car_cmd.publish(self.car_cmd_msg)
            # ToDo: keep following last command?
        else:

            # if self.last_vehicle_pose.header.stamp.to_sec() > 0:  # skip first frame
                # delta_t = (vehicle_pose_msg.header.stamp - self.last_pose.header.stamp).to_sec()  # throughput delta
            delta_t = rospy.Time.now() - vehicle_pose_msg.header.stamp  # latency
            [delta_omega, delta_x, delta_y] = self.integrate(self.car_cmd_msg.omega, self.car_cmd_msg.v, delta_t)

            actual_x = vehicle_pose_msg.x - delta_x
            actual_y = vehicle_pose_msg.y - delta_y
            delta_dist_vec = np.array([actual_x, actual_y])
            actual_rho = np.linalg.norm(delta_dist_vec)
            actual_theta = vehicle_pose_msg.theta - delta_omega

            self.car_cmd_msg.header = vehicle_pose_msg.header
            # Following Error Calculation
            following_error = actual_rho - self.dist_ref
            self.car_cmd_msg.v = self.k_follow * following_error

            if self.car_cmd_msg.v > self.max_speed:
                self.car_cmd_msg.v = self.car_cmd_msg.v
            if self.car_cmd_msg.v < - self.max_speed:
                self.car_cmd_msg.v = - self.max_speed
            elif abs(self.car_cmd_msg.v) < self.deadspace_speed:
                self.car_cmd_msg.v = 0.0

            # Heading Error Calculation
            # ToDo try an integrator
            heading_error = actual_theta - self.head_ref

            self.car_cmd_msg.omega = self.k_heading * heading_error

            if self.car_cmd_msg.omega > self.max_heading:
                self.car_cmd_msg.omega = self.max_heading
            elif self.car_cmd_msg.omega < -self.max_heading:
                self.car_cmd_msg.omega = -self.max_heading
            elif abs(self.car_cmd_msg.omega) < self.deadspace_heading:
                self.car_cmd_msg.omega = 0.0
            # ToDo: what to do with vehicle_pose_msg.psi.data?

            self.last_omega = self.car_cmd_msg.omega
            self.last_v = self.car_cmd_msg.v

            # Publish control message
            self.pub_car_cmd.publish(self.car_cmd_msg)

        self.last_vehicle_pose = vehicle_pose_msg

        # # debugging
        # self.pub_counter += 1
        # if self.pub_counter % 50 == 0:
        #     self.pub_counter = 1
        #     print "vehicle_follow publish"
        #     print self.car_cmd_msg

    def integrate(self, theta_dot, v, dt):
        theta_delta = theta_dot * dt
        if abs(theta_dot) < 0.000001:  # to ensure no division by zero for radius calculation
            # straight line
            x_delta = v * dt
            y_delta = 0
        else:
            # arc of circle, see "Probabilitic robotics"
            radius = v / theta_dot
            x_delta = radius * np.sin(theta_delta)
            y_delta = radius * (1.0 - np.cos(theta_delta))
        return [theta_delta, x_delta, y_delta]

    def propagate(self, theta, x, y, theta_delta, x_delta, y_delta):
        theta_res = theta + theta_delta
        # arc of circle, see "Probabilistic robotics"
        x_res = x + x_delta * np.cos(theta) - y_delta * np.sin(theta)
        y_res = y + y_delta * np.cos(theta) + x_delta * np.sin(theta)
        return [theta_res, x_res, y_res]

    def integrate_propagate(self, theta, x, y, theta_dot, v, dt):
        [theta_delta, x_delta, y_delta] = self.integrate(theta_dot, v, dt)
        [theta_res, x_res, y_res] = self.propagate(theta, x, y, theta_delta, x_delta, y_delta)
        # theta_delta = theta_dot*dt
        # theta_res = theta + theta_delta
        # if (theta_dot < 0.000001):
        #     # straight line
        #     x_res = x+ cos(theta) * v * dt
        #     y_res = y+ sin(theta) * v * dt
        # else:
        #     # arc of circle, see "Probabilitic robotics"
        #     v_w_ratio = v / theta_dot
        #     x_res = x + v_w_ratio * sin(theta_res) - v_w_ratio * sin(theta)
        #     y_res = y + v_w_ratio * cos(theta) - v_w_ratio * cos(theta_res)
        return [theta_res, x_res, y_res]


if __name__ == "__main__":
    rospy.init_node("vehicle_follow_node", anonymous=False)
    lane_supervisor_node = VehicleFollow()
    rospy.spin()
